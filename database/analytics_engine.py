from typing import Optional, List, Dict, Any
from datetime import datetime
from google.cloud import firestore
from database import db, logger
from database.queries import get_monthly_expenses
import io
import csv

async def get_daily_aggregation(user_id: int, year: Optional[int] = None, month: Optional[int] = None) -> List[Dict[str, Any]]:
    """Calculates daily spent totals for a month for the dashboard chart."""
    expenses = await get_monthly_expenses(user_id, year, month)
    
    daily_totals = {}
    for _, date_str, amount, _, _, tx_type in expenses:
        if tx_type == 'expense' and date_str:
            try:
                # ISO format '2026-03-02T...' -> '2026-03-02'
                day = date_str.split('T')[0]
                daily_totals[day] = daily_totals.get(day, 0.0) + float(amount)
            except:
                continue
    
    # Sort by date
    sorted_days = sorted(daily_totals.keys())
    return [{"date": day, "spent": daily_totals[day]} for day in sorted_days]

async def get_yearly_month_totals(user_id: int, year: Optional[int] = None) -> Dict[int, float]:
    """Returns monthly totals for a year from Firestore."""
    if year is None: year = datetime.now().year
    start_iso = datetime(year, 1, 1).isoformat()
    end_iso = datetime(year + 1, 1, 1).isoformat()
    
    user_id_str = str(user_id)
    expenses_ref = db.collection("users").document(user_id_str).collection("expenses")
    
    try:
        query = expenses_ref.where("date", ">=", start_iso).where("date", "<", end_iso)
        docs = query.stream()
        
        totals = {m: 0.0 for m in range(1, 13)}
        async for doc in docs:
            data = doc.to_dict()
            if data.get("type", "expense") == "expense" and data.get("date"):
                try:
                    month = int(data["date"][5:7])
                    totals[month] += float(data.get("amount", 0))
                except: pass
            elif data.get("date"):
                try:
                    month = int(data["date"][5:7])
                    totals[month] -= float(data.get("amount", 0))
                except: pass
        return totals
    except Exception as e:
        logger.error(f"Error getting yearly totals: {e}")
        return {}

async def get_category_totals(user_id: int, year: Optional[int] = None, month: Optional[int] = None) -> Dict[str, Dict[str, float]]:
    expenses = await get_monthly_expenses(user_id, year, month)
    totals = {}
    for _, _, amount, cat, _, tx_type in expenses:
        if cat not in totals:
            totals[cat] = {"expenses": 0.0, "income": 0.0}
        if tx_type == "expense":
            totals[cat]["expenses"] += float(amount)
        else:
            totals[cat]["income"] += float(amount)
    return totals

async def get_expense_totals(user_id: int, year: Optional[int] = None, month: Optional[int] = None) -> Dict[str, float]:
    nested = await get_category_totals(user_id, year, month)
    flat = {}
    for cat, vals in nested.items():
        if vals["expenses"] > 0:
            flat[cat] = round(vals["expenses"], 2)
    return flat

async def export_expenses_csv(user_id: int) -> str:
    user_id_str = str(user_id)
    expenses_ref = db.collection("users").document(user_id_str).collection("expenses")
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Amount', 'Category', 'Description', 'Type'])
    
    try:
        query = expenses_ref.order_by("date", direction=firestore.Query.DESCENDING)
        docs = query.stream()
        async for doc in docs:
            data = doc.to_dict()
            writer.writerow([
                data.get("date", "")[:10],
                data.get("amount", 0),
                data.get("category", ""),
                data.get("description", ""),
                data.get("type", "expense")
            ])
        return output.getvalue()
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        return output.getvalue()

async def save_insight(user_id: int, year: int, month: int, content: str) -> None:
    user_id_str = str(user_id)
    doc_id = f"{year}_{month}"
    doc_ref = db.collection("users").document(user_id_str).collection("insights").document(doc_id)
    try:
        await doc_ref.set({
            "content": content,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        logger.error(f"Error saving insight: {e}")

async def get_insight(user_id: int, year: int, month: int) -> Optional[str]:
    user_id_str = str(user_id)
    doc_id = f"{year}_{month}"
    doc_ref = db.collection("users").document(user_id_str).collection("insights").document(doc_id)
    try:
        doc = await doc_ref.get()
        if doc.exists:
            return doc.to_dict().get("content")
        return None
    except Exception as e:
        logger.error(f"Error fetching insight: {e}")
        return None

from datetime import timedelta

async def get_cash_flow_forecast(user_id: int) -> List[Dict[str, Any]]:
    """Generates a combined daily cash flow series for the last 30 and next 30 days."""
    user_id_str = str(user_id)
    expenses_ref = db.collection("users").document(user_id_str).collection("expenses")
    
    now = datetime.now()
    start_date = now - timedelta(days=30)
    end_date = now + timedelta(days=30)
    
    start_iso = start_date.isoformat()
    end_iso = end_date.isoformat()
    
    try:
        # Fetch all overlapping this -30 to +30 window
        query = expenses_ref.where("date", ">=", start_iso).where("date", "<=", end_iso)
        docs = query.stream()
        
        daily_flow = {}
        
        # Populate the dictionary with 0s for all 60 days to ensure continuity
        for i in range(61):
            day_str = (start_date + timedelta(days=i)).strftime('%Y-%m-%d')
            daily_flow[day_str] = {"historical_in": 0.0, "historical_out": 0.0, "projected_in": 0.0, "projected_out": 0.0}
            
        async for doc in docs:
            data = doc.to_dict()
            amt = float(data.get("amount", 0))
            is_income = data.get("type", "expense") == "income"
            
            status = data.get("status", "completed")
            
            # Use due_date for planned expenses, otherwise use created date
            tx_date_str = data.get("due_date") if status == "planned" and data.get("due_date") else data.get("date")
            if not tx_date_str:
                continue
                
            day = tx_date_str[:10]
            if day in daily_flow:
                if status == "completed":
                    if is_income: daily_flow[day]["historical_in"] += amt
                    else: daily_flow[day]["historical_out"] += amt
                else:
                    if is_income: daily_flow[day]["projected_in"] += amt
                    else: daily_flow[day]["projected_out"] += amt
                    
        sorted_days = sorted(daily_flow.keys())
        series = []
        
        for day in sorted_days:
            series.append({
                "date": day,
                "historical_net": daily_flow[day]["historical_in"] - daily_flow[day]["historical_out"],
                "projected_net": daily_flow[day]["projected_in"] - daily_flow[day]["projected_out"],
                "is_future": day > now.strftime('%Y-%m-%d')
            })
            
        return series
    except Exception as e:
        logger.error(f"Error getting cash flow forecast: {e}")
        return []
