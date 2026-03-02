import os
import io
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import services.database as db
import services.firestore_service as firestore_service
import services.llm_helper as llm_helper
from handlers.utils import (
    _display_category, _escape_markdown, _get_cached_profile,
    _invalidate_profile_cache, _private_only
)
from services.charts import _generate_pie_chart
from handlers.settings_ui import _show_settings, _profile_defaults
from core.config import logger, VALID_CALLBACKS


def _format_date(date_str: str) -> str:
    """Helper for formatting ISO date strings to DD/MM."""
    return date_str[8:10] + '/' + date_str[5:7]


MONTH_NAMES = ['', 'January', 'February', 'March', 'April', 'May', 'June',
               'July', 'August', 'September', 'October', 'November', 'December']
MONTH_NAMES_SHORT = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


async def _handle_this_month_view(query, telegram_id: int, year: int, month: int, data: str):
    """Renders a rich monthly summary with budget bar."""
    spent, income = await firestore_service.get_monthly_summary(telegram_id, year, month)
    budget = await firestore_service.get_budget(telegram_id)
    net = income - spent

    text = f"📅 *{MONTH_NAMES[month]} {year}*\n\n"
    text += f"📥 *Income:* 🟢 ₪{income:,.2f}\n"
    text += f"📤 *Expenses:* 🔴 ₪{spent:,.2f}\n"
    text += f"🧮 *Net Flow:* ₪{net:,.2f}\n\n"

    if budget and spent > 0:
        pct = (spent / budget) * 100
        bar_len = 10
        filled = min(bar_len, int((pct / 100) * bar_len))
        bar = "▮" * filled + "▯" * (bar_len - filled)
        text += f"📊 *Budget:* [{bar}] {pct:.0f}%\n"
        text += f"_(₪{spent:,.2f} of ₪{budget:,.2f})_\n\n"

    text += "🔽 *Recent Transactions:*\n"

    expenses = await asyncio.to_thread(db.get_monthly_expenses, telegram_id, year, month)
    if not expenses:
        text += "_No transactions logged._"
    else:
        for exp in expenses[:5]:
            d_str = _format_date(exp[1])
            icon = "🟢" if exp[5] == "income" else "🔴"
            cat = _display_category(exp[3])
            desc = f" — _{_escape_markdown(exp[4])}_" if exp[4] else ""
            text += f"• {d_str} | {cat}: {icon} ₪{exp[2]:.0f}{desc}\n"

    is_current = data == 'this_month'
    buttons = [
        [InlineKeyboardButton("🗑️ Delete All This Month", callback_data='delete_all_monthly')],
        [InlineKeyboardButton("⬅️ Back", callback_data='monthly_list')],
    ] if is_current else [
        [InlineKeyboardButton("⬅️ Back to Year", callback_data='year_overview')]
    ]
    await query.edit_message_text(text=text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))


@_private_only
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    telegram_id = query.from_user.id
    data = query.data

    # ── Confirmation Guards (always handled first) ──
    if data == 'confirm_delete_all':
        count = await asyncio.to_thread(db.delete_all_expenses, telegram_id)
        await query.edit_message_text(
            text=f"🗑️ *Done!* Deleted {count} expense(s).\n\nYou're starting fresh.",
            parse_mode='Markdown'
        )
        return

    if data == 'cancel_delete_all':
        await query.edit_message_text(text="✅ Cancelled. Your expenses are safe.")
        return

    if data == 'confirm_delete_monthly':
        count = await asyncio.to_thread(db.delete_monthly_expenses, telegram_id)
        await query.edit_message_text(
            text=f"🗑️ *Done!* Deleted {count} expense(s) from this month.\n\nUse /menu to continue.",
            parse_mode='Markdown'
        )
        return

    if data == 'cancel_delete_monthly':
        await query.edit_message_text(text="✅ Cancelled. Your monthly expenses are safe.")
        return

    # ── Prefix-Based Dynamic Callbacks ──

    if data.startswith("del_"):
        try:
            expense_id = int(data[4:])
            success = await asyncio.to_thread(db.delete_expense, telegram_id, expense_id)
            if success:
                await query.edit_message_text(
                    text="🗑️ *Expense deleted!*\n\nUse /menu to refresh.", parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(text="⚠️ Could not delete. It may already be removed.")
        except Exception:
            await query.edit_message_text(text="⚠️ Error deleting expense.")
        return

    if data.startswith("month_"):
        # Drill-down into a specific year/month (e.g. "month_2026_2")
        try:
            parts = data.split('_')
            year, month = int(parts[1]), int(parts[2])
            await _handle_this_month_view(query, telegram_id, year, month, data)
        except Exception as e:
            logger.error(f"Error in month drill-down: {type(e).__name__}: {e}")
            await query.edit_message_text(text="⚠️ Error loading month data.")
        return

    if data.startswith("lang_"):
        lang_name = data[5:]
        valid_langs = {'English', 'Hebrew', 'Spanish', 'French', 'German', 'Russian', 'Arabic', 'Portuguese'}
        if lang_name in valid_langs:
            try:
                profile = await firestore_service.get_profile(telegram_id)
                p = _profile_defaults(profile)
                await firestore_service.set_profile(
                    telegram_id,
                    p['age'], p['yearly_income'], p['currency'], lang_name, p['additional_info']
                )
                _invalidate_profile_cache(telegram_id)
                await _show_settings(query, telegram_id, telegram_id, edit=True)
            except Exception:
                await query.edit_message_text(text="⚠️ Error updating language. Please try again.")
        return

    if data.startswith("cur_"):
        cur_code = data[4:]
        valid_curs = {'NIS', 'USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY'}
        if cur_code in valid_curs:
            try:
                profile = await firestore_service.get_profile(telegram_id)
                p = _profile_defaults(profile)
                await firestore_service.set_profile(
                    telegram_id,
                    p['age'], p['yearly_income'], cur_code, p['language'], p['additional_info']
                )
                _invalidate_profile_cache(telegram_id)
                await _show_settings(query, telegram_id, telegram_id, edit=True)
            except Exception:
                await query.edit_message_text(text="⚠️ Error updating currency. Please try again.")
        return

    if data.startswith("cat_select_"):
        cat_name = data[11:]
        pending = context.user_data.get('pending_expense')
        if not pending:
            await query.edit_message_text(
                text="⚠️ Session expired. Please send the expense message again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')]])
            )
            return
        amount = pending['amount']
        description = pending['description']
        await firestore_service.add_expense(telegram_id, amount, cat_name, description)
        context.user_data.pop('pending_expense', None)
        safe_desc = _escape_markdown(description)
        response_text = (
            f"✅ *Expense Saved!*\n\n"
            f"💰 Amount: 🔴 *₪{amount:.2f}*\n"
            f"📂 Category: {_display_category(cat_name)}\n"
            f"📝 Details: _{safe_desc}_\n\n"
            f"Use /menu to see your dashboard."
        )
        await query.edit_message_text(
            text=response_text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ Undo", callback_data='undo_last'),
                 InlineKeyboardButton("📊 Dashboard", callback_data='back_to_menu')]
            ])
        )
        return

    if data == 'cancel_cat_select':
        context.user_data.pop('pending_expense', None)
        await query.edit_message_text(
            text="❌ Expense cancelled.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')]])
        )
        return

    # ── Whitelist Check for Static Callbacks ──
    if data not in VALID_CALLBACKS:
        logger.warning(f"Invalid callback data from user {telegram_id}: '{data}' rejected")
        return

    # ── Static Callback Handlers ──
    try:
        if data == 'last_expenses':
            expenses = await asyncio.to_thread(db.get_recent_expenses, user_id=telegram_id, limit=5)
            if not expenses:
                await query.edit_message_text(
                    text="📭 No expenses found yet.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data='back_to_menu')]])
                )
            else:
                text = "📜 *Last 5 Expenses:*\n\n"
                buttons = []
                for exp in expenses:
                    date_short = exp[1][5:10]
                    safe_desc = _escape_markdown(exp[4] or '')
                    text += f"🗓️ `{date_short}` | 💰 *{exp[2]}* | {_display_category(exp[3])}\n_{safe_desc}_\n\n"
                    buttons.append([InlineKeyboardButton(
                        f"🗑️ Delete ₪{exp[2]} {_display_category(exp[3])}",
                        callback_data=f"del_{exp[0]}"
                    )])
                buttons.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')])
                await query.edit_message_text(
                    text=text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons)
                )

        elif data == 'monthly_list':
            keyboard = [
                [InlineKeyboardButton("📅 This Month", callback_data='this_month')],
                [InlineKeyboardButton("📆 Yearly Overview", callback_data='year_overview')],
                [InlineKeyboardButton("⬅️ Back to Menu", callback_data='back_to_menu')],
            ]
            await query.edit_message_text(
                text="📊 *Expense History*\n\nChoose a view:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == 'this_month':
            now = datetime.now()
            await _handle_this_month_view(query, telegram_id, now.year, now.month, data)

        elif data == 'year_overview':
            now = datetime.now()
            year = now.year
            month_totals = await asyncio.to_thread(db.get_yearly_month_totals, telegram_id, year)
            if not month_totals:
                await query.edit_message_text(
                    text=f"📆 No expenses in {year} yet.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data='monthly_list')]])
                )
                return
            grand_total = sum(month_totals.values())
            text = f"📆 *{year} Yearly Overview*\n💰 *Grand Total: ₪{grand_total:,.2f}*\n\n"
            buttons = []
            for m in range(1, 13):
                total = month_totals.get(m, 0)
                if total > 0:
                    pct = (total / grand_total) * 100
                    text += f"📌 *{MONTH_NAMES_SHORT[m]}*: ₪{total:,.2f} ({pct:.0f}%)\n"
                    buttons.append([InlineKeyboardButton(
                        f"📅 {MONTH_NAMES_SHORT[m]} — ₪{total:,.0f}",
                        callback_data=f'month_{year}_{m}'
                    )])
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data='monthly_list')])
            await query.edit_message_text(
                text=text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons)
            )

        elif data == 'back_to_menu':
            from telegram import WebAppInfo
            webapp_url = os.getenv("WEBAPP_URL", "https://your-ngrok-url.ngrok-free.app/webapp")
            keyboard = [
                [InlineKeyboardButton("🌐 Open Web Dashboard", web_app=WebAppInfo(url=webapp_url))],
                [InlineKeyboardButton("📜 Last Transactions", callback_data='last_expenses'),
                 InlineKeyboardButton("📅 Monthly / Yearly", callback_data='monthly_list')],
                [InlineKeyboardButton("📊 Category Pie Chart", callback_data='pie_chart'),
                 InlineKeyboardButton("💡 AI Context Insights", callback_data='insights')],
                [InlineKeyboardButton("⚙️ Settings & Tools", callback_data='settings_tools')],
            ]
            await query.edit_message_text(
                text='📊 *My Finances Dashboard:*',
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

        elif data == 'delete_all_monthly':
            keyboard = [
                [InlineKeyboardButton("🗑️ Yes, delete this month", callback_data='confirm_delete_monthly')],
                [InlineKeyboardButton("❌ Cancel", callback_data='cancel_delete_monthly')],
            ]
            await query.edit_message_text(
                text="⚠️ *Are you sure you want to delete ALL expenses for this month?*\n\nThis action *cannot be undone!*",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == 'pie_chart':
            totals = await asyncio.to_thread(db.get_expense_totals, telegram_id)
            if not totals:
                await query.edit_message_text(text="📉 No data for a chart yet.")
                return
            total_sum = sum(totals.values())
            if total_sum <= 0:
                await query.edit_message_text(text="📉 No valid data for a chart.")
                return
            await query.edit_message_text(text="📊 *Generating Expense Breakdown...*", parse_mode='Markdown')
            chart_buf = await asyncio.to_thread(_generate_pie_chart, totals, total_sum)
            caption = f"📊 *Expense Breakdown*\n🔴 *Total Spent: ₪{total_sum:,.2f}*\n\n"
            for cat, amt in sorted(totals.items(), key=lambda x: x[1], reverse=True):
                pct = (amt / total_sum) * 100
                caption += f"• {_display_category(cat)}: ₪{amt:,.2f} ({pct:.0f}%)\n"
            back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')]])
            if chart_buf is None:
                await query.edit_message_text(
                    text="⚠️ Chart generation failed. Here is your text breakdown:\n\n" + caption,
                    reply_markup=back_btn, parse_mode='Markdown'
                )
            else:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id, photo=chart_buf,
                    caption=caption, reply_markup=back_btn, parse_mode='Markdown'
                )

        elif data == 'insights':
            await query.edit_message_text(
                text="🧠 *Analyzing your spending...*\n\n_This might take a moment._",
                parse_mode='Markdown'
            )
            try:
                raw_totals = await asyncio.to_thread(db.get_category_totals, telegram_id)
                totals = {cat: v.get('expenses', 0) for cat, v in raw_totals.items() if v.get('expenses', 0) > 0}
                if not totals:
                    await query.edit_message_text(
                        text="💡 No spending data yet. Log some expenses first!", parse_mode='Markdown'
                    )
                    return
                budget = await firestore_service.get_budget(telegram_id)
                recent = await asyncio.to_thread(db.get_recent_expenses, user_id=telegram_id, limit=5)
                profile = await firestore_service.get_profile(telegram_id)
                insight = await asyncio.to_thread(
                    llm_helper.generate_insights,
                    totals=totals,
                    age=profile.get('age') if profile else None,
                    yearly_income=profile.get('yearly_income') if profile else None,
                    budget=budget,
                    recent_expenses=recent,
                    currency=profile.get('currency', 'NIS') if profile else 'NIS',
                    language=profile.get('language', 'English') if profile else 'English',
                    additional_info=profile.get('additional_info', '') if profile else None
                )
                if not insight or "⚠️" in insight:
                    await query.edit_message_text(
                        text="⚠️ *AI Engine Unavailable*\n\nCould not generate insights at this time.",
                        parse_mode='Markdown'
                    )
                    return
                now = datetime.now()
                await asyncio.to_thread(db.save_insight, telegram_id, now.year, now.month, insight)
                safe_insight = _escape_markdown(insight)
                await query.edit_message_text(
                    text=f"💡 *FinTechBot Insights:*\n\n{safe_insight}", 
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')]])
                )
            except Exception as e:
                logger.error(f"Error generating insights: {e}")
                await query.edit_message_text(
                    text="⚠️ *Error*\n\nThe AI ran into an issue. Please try again later.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')]])
                )

        elif data in ('settings_menu', 'settings_tools'):
            context.user_data.pop('awaiting_setting', None)
            await _show_settings(query, telegram_id, telegram_id, edit=True)

        elif data == 'settings_set_lang':
            keyboard = [
                [InlineKeyboardButton("🇬🇧 English", callback_data='lang_English'),
                 InlineKeyboardButton("🇮🇱 Hebrew", callback_data='lang_Hebrew')],
                [InlineKeyboardButton("🇪🇸 Spanish", callback_data='lang_Spanish'),
                 InlineKeyboardButton("🇫🇷 French", callback_data='lang_French')],
                [InlineKeyboardButton("🇩🇪 German", callback_data='lang_German'),
                 InlineKeyboardButton("🇷🇺 Russian", callback_data='lang_Russian')],
                [InlineKeyboardButton("🇸🇦 Arabic", callback_data='lang_Arabic'),
                 InlineKeyboardButton("🇧🇷 Portuguese", callback_data='lang_Portuguese')],
                [InlineKeyboardButton("✏️ Other (type it)", callback_data='settings_edit_lang_custom')],
                [InlineKeyboardButton("⬅️ Back", callback_data='settings_tools')],
            ]
            await query.edit_message_text(
                text="🌐 *Choose your language:*\n\n_AI insights and all bot responses will be in this language._",
                parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == 'settings_edit_lang_custom':
            context.user_data['awaiting_setting'] = 'lang_custom'
            await query.edit_message_text(
                text="✏️ *Type your preferred language:*\n_(e.g. Italian, Thai, Turkish)_",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='settings_tools')]])
            )

        elif data == 'settings_set_currency':
            keyboard = [
                [InlineKeyboardButton("🇮🇱 NIS ₪", callback_data='cur_NIS'),
                 InlineKeyboardButton("🇺🇸 USD $", callback_data='cur_USD')],
                [InlineKeyboardButton("🇪🇺 EUR €", callback_data='cur_EUR'),
                 InlineKeyboardButton("🇬🇧 GBP £", callback_data='cur_GBP')],
                [InlineKeyboardButton("🇨🇦 CAD", callback_data='cur_CAD'),
                 InlineKeyboardButton("🇦🇺 AUD", callback_data='cur_AUD')],
                [InlineKeyboardButton("🇯🇵 JPY ¥", callback_data='cur_JPY')],
                [InlineKeyboardButton("✏️ Other (type it)", callback_data='settings_edit_currency_custom')],
                [InlineKeyboardButton("⬅️ Back", callback_data='settings_tools')],
            ]
            await query.edit_message_text(
                text="💱 *Choose your primary currency:*\n\n_Used for income tracking and AI insights._",
                parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == 'settings_edit_currency_custom':
            context.user_data['awaiting_setting'] = 'currency_custom'
            await query.edit_message_text(
                text="✏️ *Type your currency code:*\n_(e.g. CHF, TRY, BRL)_",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='settings_tools')]])
            )

        elif data == 'settings_set_budget':
            budget = await firestore_service.get_budget(telegram_id)
            total, _ = await firestore_service.get_monthly_summary(telegram_id)
            context.user_data['awaiting_setting'] = 'budget'
            budget_text = (
                f"Current: *₪{budget:,.0f}*, spent *₪{total:,.0f}* this month." if budget
                else "_No budget set yet._"
            )
            await query.edit_message_text(
                text=f"💰 *Set Monthly Budget*\n\n{budget_text}\n\n✏️ Type your new monthly budget amount:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='settings_tools')]])
            )

        elif data == 'settings_set_age':
            profile = await firestore_service.get_profile(telegram_id)
            current = (
                f"Current: *{profile['age']}*"
                if profile and profile.get('age') else "_Not set yet._"
            )
            context.user_data['awaiting_setting'] = 'age'
            await query.edit_message_text(
                text=f"👤 *Set Your Age*\n\n{current}\n\n✏️ Type your age (13–120):",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='settings_tools')]])
            )

        elif data == 'settings_set_income':
            profile = await firestore_service.get_profile(telegram_id)
            currency = profile.get('currency', 'NIS') if profile else 'NIS'
            income_val = profile.get('yearly_income', 0) if profile else 0
            current = (
                f"Current: *{income_val:,.0f} {currency} / year*"
                if income_val else "_Not set yet._"
            )
            context.user_data['awaiting_setting'] = 'income'
            await query.edit_message_text(
                text=f"💵 *Set Annual Income*\n\n{current}\n\n✏️ Type your yearly income:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='settings_tools')]])
            )

        elif data == 'settings_set_goals':
            profile = await firestore_service.get_profile(telegram_id)
            current = (
                f"_Current:_ {_escape_markdown(profile['additional_info'])}"
                if profile and profile.get('additional_info') else "_Not set yet._"
            )
            context.user_data['awaiting_setting'] = 'goals'
            await query.edit_message_text(
                text=(
                    f"🎯 *Financial Goals & Context*\n\n{current}\n\n"
                    "✏️ Describe your financial goals:\n"
                    "_e.g. 'Saving for a mortgage', 'Clearing student debt', 'FIRE by 40'_\n\n"
                    "_(Send 'none' to clear)_"
                ),
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='settings_tools')]])
            )

        elif data == 'undo_last':
            last_id = await asyncio.to_thread(db.get_last_expense_id, telegram_id)
            if not last_id:
                await query.edit_message_text(
                    text="📭 No expenses to undo.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data='back_to_menu')]])
                )
            else:
                success = await asyncio.to_thread(db.delete_expense, telegram_id, last_id)
                if success:
                    await query.edit_message_text(
                        text="↩️ *Last expense removed!*",
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')]])
                    )
                else:
                    await query.edit_message_text(
                        text="⚠️ Could not undo. Try again.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data='back_to_menu')]])
                    )

        elif data == 'export_csv':
            csv_data = await asyncio.to_thread(db.export_expenses_csv, telegram_id)
            if not csv_data or csv_data.strip() == 'Date,Amount,Category,Description':
                await query.edit_message_text(
                    text="📭 No expenses to export.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data='back_to_menu')]])
                )
            else:
                file = io.BytesIO(csv_data.encode('utf-8'))
                file.name = "expenses.csv"
                await context.bot.send_document(
                    chat_id=telegram_id, document=file,
                    caption="📤 *Your expenses export*", parse_mode='Markdown'
                )
                await query.edit_message_text(
                    text="✅ Export sent successfully!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')]])
                )

        elif data == 'delete_all':
            keyboard = [
                [InlineKeyboardButton("🗑️ Yes, wipe EVERYTHING", callback_data='confirm_delete_all')],
                [InlineKeyboardButton("❌ Cancel", callback_data='cancel_delete_all')],
            ]
            await query.edit_message_text(
                text="⚠️ *Are you absolutely sure you want to delete ALL your data?*\n\nThis action *cannot be undone!*",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    except Exception as e:
        logger.error(f"Error in button_handler for user {telegram_id}: {type(e).__name__}: {e}")
        try:
            await query.edit_message_text(text="⚠️ Something went wrong. Please try again.")
        except Exception:
            pass
