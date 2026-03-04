"""
Localization module for FinTechBot.
Provides translations for all UI strings across the bot.
"""

TRANSLATIONS: dict[str, dict[str, str]] = {
    # ---------------------------------------------------------------------------
    # ONBOARDING
    # ---------------------------------------------------------------------------
    "welcome_new": {
        "English": "🏦 *Welcome to FinTechBot Premium.*\n\nI am your Personal Wealth Manager.\n\n",
        "Hebrew":  "🏦 *ברוכים הבאים ל-FinTechBot Premium.*\n\nאני מנהל הון אישי שלך.\n\n",
        "Spanish": "🏦 *Bienvenido a FinTechBot Premium.*\n\nSoy tu Gestor de Riqueza Personal.\n\n",
        "French":  "🏦 *Bienvenue sur FinTechBot Premium.*\n\nJe suis votre Gestionnaire de Patrimoine Personnel.\n\n",
    },
    "welcome_restart": {
        "English": "🔄 *Onboarding Restarted*\n\nLet's set up your profile from scratch.\n\n",
        "Hebrew":  "🔄 *ההרשמה הופעלה מחדש*\n\nבואו נגדיר את הפרופיל שלך מחדש.\n\n",
        "Spanish": "🔄 *Incorporación reiniciada*\n\nConfiguremos tu perfil desde cero.\n\n",
        "French":  "🔄 *Intégration Redémarrée*\n\nConfigurons votre profil depuis le début.\n\n",
    },
    "choose_language": {
        "English": "🌐 *First, please choose your language:*\n_All insights will be in this language._",
        "Hebrew":  "🌐 *ראשית, בחר את השפה שלך:*\n_כל התובנות יהיו בשפה זו._",
        "Spanish": "🌐 *Primero, elige tu idioma:*\n_Todos los análisis estarán en este idioma._",
        "French":  "🌐 *D'abord, choisissez votre langue:*\n_Tous les insights seront dans cette langue._",
    },
    "lang_set": {
        "English": "✅ Language set to English.\n\n💱 *Now, choose your primary currency:*",
        "Hebrew":  "✅ שפה הוגדרה לעברית.\n\n💱 *כעת, בחר את המטבע הראשי שלך:*",
        "Spanish": "✅ Idioma establecido en Español.\n\n💱 *Ahora, elige tu moneda principal:*",
        "French":  "✅ Langue définie en Français.\n\n💱 *Maintenant, choisissez votre devise principale:*",
    },
    "currency_set": {
        "English": "✅ Currency set to {cur}.\n\n🛠 *What type of account do you need?*\n\n_Small Business enables future tracking and cash flow forecasting._",
        "Hebrew":  "✅ המטבע הוגדר ל-{cur}.\n\n🛠 *איזה סוג חשבון אתה צריך?*\n\n_עסק קטן מאפשר מעקב עתידי ותחזית תזרים מזומנים._",
        "Spanish": "✅ Moneda establecida en {cur}.\n\n🛠 *¿Qué tipo de cuenta necesitas?*\n\n_Pequeñas empresas permite rastreo futuro y previsión de flujo de caja._",
        "French":  "✅ Devise définie sur {cur}.\n\n🛠 *Quel type de compte souhaitez-vous?*\n\n_Petite entreprise permet un suivi futur et des prévisions de flux de trésorerie._",
    },
    "account_set_budget_prompt": {
        "English": "✅ Account type set to {acct}.\n\n💰 *Finally, type your monthly budget amount:*\n_(e.g., 5000)_",
        "Hebrew":  "✅ סוג החשבון הוגדר ל-{acct}.\n\n💰 *לבסוף, הקלד את סכום התקציב החודשי שלך:*\n_(לדוגמה, 5000)_",
        "Spanish": "✅ Tipo de cuenta establecido en {acct}.\n\n💰 *Finalmente, escribe tu presupuesto mensual:*\n_(ej., 5000)_",
        "French":  "✅ Type de compte défini sur {acct}.\n\n💰 *Enfin, tapez votre budget mensuel:*\n_(ex. 5000)_",
    },
    "budget_invalid": {
        "English": "⚠️ Invalid input. Please type a positive number for your budget (e.g. 5000):",
        "Hebrew":  "⚠️ קלט לא תקין. אנא הקלד מספר חיובי עבור התקציב שלך (לדוגמה 5000):",
        "Spanish": "⚠️ Entrada inválida. Por favor escribe un número positivo para tu presupuesto (ej. 5000):",
        "French":  "⚠️ Entrée invalide. Veuillez entrer un nombre positif pour votre budget (ex. 5000):",
    },
    "setup_complete": {
        "English": "✅ *Setup Complete!*\nMonthly budget set to {amount}.\n\nYou can now start logging expenses or open your dashboard below.",
        "Hebrew":  "✅ *ההגדרה הושלמה!*\nתקציב חודשי הוגדר ל-{amount}.\n\nכעת תוכל להתחיל לרשום הוצאות או לפתוח את לוח הבקרה שלך למטה.",
        "Spanish": "✅ *¡Configuración Completada!*\nPresupuesto mensual establecido en {amount}.\n\nYa puedes registrar gastos o abrir tu panel de control abajo.",
        "French":  "✅ *Configuration Terminée!*\nBudget mensuel fixé à {amount}.\n\nVous pouvez maintenant commencer à enregistrer des dépenses ou ouvrir votre tableau de bord ci-dessous.",
    },
    "web_dashboard_added": {
        "English": "A persistent Web Dashboard button has been added to your keyboard! 👇",
        "Hebrew":  "כפתור לוח הבקרה Web נוסף למקלדת שלך! 👇",
        "Spanish": "¡Se ha añadido un botón del Panel Web a tu teclado! 👇",
        "French":  "Un bouton du Tableau de Bord Web a été ajouté à votre clavier! 👇",
    },
    # ---------------------------------------------------------------------------
    # MAIN MENU BUTTONS
    # ---------------------------------------------------------------------------
    "btn_open_dashboard": {
        "English": "🌐 Open Web Dashboard",
        "Hebrew":  "🌐 פתח את לוח הבקרה",
        "Spanish": "🌐 Abrir Panel Web",
        "French":  "🌐 Ouvrir le Tableau de Bord",
    },
    "btn_last_transactions": {
        "English": "📜 Last Transactions",
        "Hebrew":  "📜 עסקאות אחרונות",
        "Spanish": "📜 Últimas Transacciones",
        "French":  "📜 Dernières Transactions",
    },
    "btn_monthly_yearly": {
        "English": "📅 Monthly / Yearly",
        "Hebrew":  "📅 חודשי / שנתי",
        "Spanish": "📅 Mensual / Anual",
        "French":  "📅 Mensuel / Annuel",
    },
    "btn_pie_chart": {
        "English": "📊 Category Pie Chart",
        "Hebrew":  "📊 תרשים עוגה לפי קטגוריה",
        "Spanish": "📊 Gráfico de Categorías",
        "French":  "📊 Graphique en Secteurs",
    },
    "btn_ai_insights": {
        "English": "💡 AI Context Insights",
        "Hebrew":  "💡 תובנות AI",
        "Spanish": "💡 Análisis de IA",
        "French":  "💡 Analyses IA",
    },
    "btn_pending_forecast": {
        "English": "📅 Pending & Forecast",
        "Hebrew":  "📅 תשלומים עתידיים ותחזית",
        "Spanish": "📅 Pendientes y Pronóstico",
        "French":  "📅 En Attente & Prévision",
    },
    "btn_settings": {
        "English": "⚙️ Settings & Tools",
        "Hebrew":  "⚙️ הגדרות וכלים",
        "Spanish": "⚙️ Ajustes y Herramientas",
        "French":  "⚙️ Paramètres et Outils",
    },
    # ---------------------------------------------------------------------------
    # EXPENSE RECEIPT MESSAGES
    # ---------------------------------------------------------------------------
    "expense_saved": {
        "English": "✅ *Expense saved!*",
        "Hebrew":  "✅ *ההוצאה נשמרה!*",
        "Spanish": "✅ *¡Gasto guardado!*",
        "French":  "✅ *Dépense enregistrée!*",
    },
    "income_saved": {
        "English": "✅ *Income saved!*",
        "Hebrew":  "✅ *ההכנסה נשמרה!*",
        "Spanish": "✅ *¡Ingreso guardado!*",
        "French":  "✅ *Revenu enregistré!*",
    },
    "not_expense_hint": {
        "English": (
            "👋 Hey! I'm your expense tracker bot.\n"
            "Send me what you spent, like:\n"
            "• *\"Spent 50 on food\"*\n"
            "• *\"taxi 35\"*\n\n"
            "Or use /menu for your dashboard."
        ),
        "Hebrew": (
            "👋 היי! אני בוט מעקב ההוצאות שלך.\n"
            "שלח לי מה הוצאת, לדוגמה:\n"
            "• *\"הוצאתי 50 על אוכל\"*\n"
            "• *\"מונית 35\"*\n\n"
            "או השתמש ב-/menu לגישה ללוח הבקרה."
        ),
        "Spanish": (
            "👋 ¡Hola! Soy tu bot de seguimiento de gastos.\n"
            "Cuéntame qué gastaste, ej.:\n"
            "• *\"Gasté 50 en comida\"*\n"
            "• *\"taxi 35\"*\n\n"
            "O usa /menu para tu panel."
        ),
        "French": (
            "👋 Salut! Je suis votre bot de suivi des dépenses.\n"
            "Dites-moi ce que vous avez dépensé, ex.:\n"
            "• *\"Dépensé 50 pour la nourriture\"*\n"
            "• *\"taxi 35\"*\n\n"
            "Ou utilisez /menu pour votre tableau de bord."
        ),
    },
    # ---------------------------------------------------------------------------
    # HELP COMMAND
    # ---------------------------------------------------------------------------
    "help_text": {
        "English": (
            "🤖 *FinTechBot Protocol:*\n\n"
            "To log an expense, simply type it out. E.g., _\"Flight to London 450 EUR\"_.\n\n"
            "You can manage your analytics and settings using the Dashboard below:"
        ),
        "Hebrew": (
            "🤖 *פרוטוקול FinTechBot:*\n\n"
            "כדי לרשום הוצאה, פשוט הקלד אותה. לדוגמה: _\"טיסה ללונדון 450 EUR\"_.\n\n"
            "תוכל לנהל את הנתונים וההגדרות שלך דרך לוח הבקרה למטה:"
        ),
        "Spanish": (
            "🤖 *Protocolo FinTechBot:*\n\n"
            "Para registrar un gasto, simplemente escríbelo. Ej., _\"Vuelo a Londres 450 EUR\"_.\n\n"
            "Puedes gestionar tus análisis y ajustes desde el panel inferior:"
        ),
        "French": (
            "🤖 *Protocole FinTechBot:*\n\n"
            "Pour enregistrer une dépense, tapez-la simplement. Ex., _\"Vol pour Londres 450 EUR\"_.\n\n"
            "Vous pouvez gérer vos analyses et paramètres via le tableau de bord ci-dessous:"
        ),
    },
    # ---------------------------------------------------------------------------
    # /menu command
    # ---------------------------------------------------------------------------
    "menu_text": {
        "English": "📊 *Your Dashboard*\n_Select an option:_",
        "Hebrew":  "📊 *לוח הבקרה שלך*\n_בחר אפשרות:_",
        "Spanish": "📊 *Tu Panel*\n_Selecciona una opción:_",
        "French":  "📊 *Votre Tableau de Bord*\n_Sélectionnez une option:_",
    },
}

_FALLBACK = "English"


def t(key: str, language: str, **kwargs) -> str:
    """
    Look up a translation by key and language.
    Falls back to English if the language or key is not found.
    Supports keyword-arg string formatting (e.g., t('setup_complete', lang, amount='5,000')).
    """
    lang_map = TRANSLATIONS.get(key, {})
    text = lang_map.get(language) or lang_map.get(_FALLBACK, f"[{key}]")
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text
