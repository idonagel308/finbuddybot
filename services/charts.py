import io
import logging

from core.config import logger
from handlers.utils import _display_category

# Category colors — vibrant, distinct, modern palette
CATEGORY_COLORS = {
    'Food':          '#FF6B6B',  # Coral red
    'Transport':     '#4ECDC4',  # Teal
    'Housing':       '#45B7D1',  # Sky blue
    'Entertainment': '#F7DC6F',  # Gold
    'Shopping':      '#BB8FCE',  # Lavender
    'Health':        '#58D68D',  # Green
    'Education':     '#5DADE2',  # Blue
    'Financial':     '#F0B27A',  # Peach
    'Other':         '#AEB6BF',  # Gray
}


def _generate_pie_chart(totals: dict, total_sum: float) -> io.BytesIO:
    """
    Generates a professional donut pie chart image and returns it as a BytesIO buffer.
    """
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend (no GUI needed)
    import matplotlib.pyplot as plt
    import numpy as np
    try:
        # Sort by amount descending
        sorted_items = sorted(totals.items(), key=lambda x: x[1], reverse=True)
        labels = []
        sizes = []
        colors = []

        for cat, amount in sorted_items:
            percent = (amount / total_sum) * 100
            labels.append(f"{_display_category(cat)}\n₪{amount:,.0f} ({percent:.0f}%)")
            sizes.append(amount)
            colors.append(CATEGORY_COLORS.get(cat, '#AEB6BF'))

        # Create figure with dark background
        fig, ax = plt.subplots(figsize=(8, 8), facecolor='#1a1a2e')
        ax.set_facecolor('#1a1a2e')

        # Draw donut chart
        wedges, texts = ax.pie(
            sizes,
            colors=colors,
            startangle=90,
            pctdistance=0.80,
            wedgeprops=dict(width=0.45, edgecolor='#1a1a2e', linewidth=2.5),
        )

        # Add labels outside the chart
        for i, (wedge, label) in enumerate(zip(wedges, labels)):
            angle = (wedge.theta2 + wedge.theta1) / 2
            x = np.cos(np.radians(angle))
            y = np.sin(np.radians(angle))
            ha = 'left' if x > 0 else 'right'
            ax.annotate(
                label,
                xy=(x * 0.78, y * 0.78),
                xytext=(x * 1.35, y * 1.35),
                fontsize=11,
                fontweight='bold',
                color='white',
                ha=ha,
                va='center',
                arrowprops=dict(arrowstyle='-', color='#ffffff55', lw=1.2),
            )

        # Center text — total amount
        ax.text(0, 0.06, 'TOTAL', ha='center', va='center',
                fontsize=14, color='#ffffffaa', fontweight='bold')
        ax.text(0, -0.08, f'₪{total_sum:,.0f}', ha='center', va='center',
                fontsize=22, color='white', fontweight='bold')

        # Title
        ax.set_title('Monthly Spending', fontsize=18, color='white',
                     fontweight='bold', pad=20)

        plt.tight_layout()

        # Save to buffer
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=90, bbox_inches='tight',
                    facecolor=fig.get_facecolor(), edgecolor='none')

        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"Error generating pie chart: {type(e).__name__} - {e}")
        return None
