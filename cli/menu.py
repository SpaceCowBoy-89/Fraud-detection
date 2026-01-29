"""
Menu System for Fraud Detection CLI

Provides:
- Grouped menu structure
- Help system
- Quick command shortcuts
- Navigation
"""

from rich.table import Table
from rich.panel import Panel
from rich import box
from .helpers import console, CLIHelpers


# Menu group definitions
MENU_GROUPS = {
    'data': {
        'icon': '📥',
        'title': 'DATA',
        'items': [
            {'key': '1', 'label': 'Fetch New Data', 'method': 'fetch_data_menu', 'shortcut': 'f', 'help': 'Fetch leads/sales from API'},
        ]
    },
    'detection': {
        'icon': '🔍',
        'title': 'DETECTION',
        'items': [
            {'key': '2', 'label': 'Run Fraud Analysis', 'method': 'run_fraud_detection', 'shortcut': 'r', 'help': 'Analyze accounts for fraud patterns'},
            {'key': '3', 'label': 'View Reports', 'method': 'view_reports', 'shortcut': 'v', 'help': 'View fraud detection reports'},
            {'key': '4', 'label': 'High-Risk Alerts', 'method': 'check_high_risk_alerts', 'shortcut': 'a', 'help': 'View high-risk flagged accounts'},
            {'key': '5', 'label': 'Test Single Email', 'method': 'test_single_email', 'shortcut': 't', 'help': 'Test fraud detection on one email'},
        ]
    },
    'analysis': {
        'icon': '📊',
        'title': 'ADVANCED ANALYSIS',
        'items': [
            {'key': '6', 'label': 'Temporal Analysis', 'method': 'temporal_analysis', 'shortcut': None, 'help': 'Analyze fraud trends over time'},
            {'key': '7', 'label': 'Pattern Discovery', 'method': 'pattern_discovery', 'shortcut': None, 'help': 'Discover fraud patterns in data'},
            {'key': '8', 'label': 'Cluster Analysis', 'method': 'cluster_analysis', 'shortcut': None, 'help': 'Find account clusters (IP, domain, geo)'},
            {'key': '9', 'label': 'Anomaly Detection', 'method': 'ensemble_anomaly_detection', 'shortcut': None, 'help': 'ML-based anomaly detection'},
            {'key': '10', 'label': 'Drift Monitoring', 'method': 'drift_monitoring', 'shortcut': None, 'help': 'Monitor for fraud pattern changes'},
            {'key': '11', 'label': 'Billing Correlations', 'method': 'billing_correlation_analysis', 'shortcut': 'b', 'help': 'Find shared billing fraud rings'},
        ]
    },
    'review': {
        'icon': '✅',
        'title': 'REVIEW & METRICS',
        'items': [
            {'key': '12', 'label': 'Record Outcomes', 'method': 'review_outcomes', 'shortcut': 'o', 'help': 'Record fraud/false positive outcomes'},
            {'key': '13', 'label': 'Effectiveness Dashboard', 'method': 'effectiveness_dashboard', 'shortcut': 'e', 'help': 'View detection effectiveness metrics'},
            {'key': '14', 'label': 'Low-Risk Sampling', 'method': 'low_risk_sampling', 'shortcut': None, 'help': 'Sample low-risk accounts for review'},
        ]
    },
    'system': {
        'icon': '⚙️',
        'title': 'SYSTEM',
        'items': [
            {'key': '15', 'label': 'Dashboard Metrics', 'method': 'view_dashboard', 'shortcut': 'd', 'help': 'View summary dashboard'},
            {'key': '16', 'label': 'Settings', 'method': 'configure_settings', 'shortcut': 's', 'help': 'Configure detection settings'},
            {'key': '17', 'label': 'View Logs', 'method': 'view_logs', 'shortcut': 'l', 'help': 'View recent log entries'},
            {'key': '18', 'label': 'Export Reports', 'method': 'export_reports', 'shortcut': None, 'help': 'Export data to CSV'},
        ]
    }
}

# Build quick command mapping
QUICK_COMMANDS = {}
ALL_MENU_ITEMS = {}

for group_key, group in MENU_GROUPS.items():
    for item in group['items']:
        ALL_MENU_ITEMS[item['key']] = item
        if item.get('shortcut'):
            QUICK_COMMANDS[item['shortcut']] = item

# Special commands
SPECIAL_COMMANDS = {
    'h': {'label': 'Help', 'help': 'Show help for current screen'},
    '?': {'label': 'Help', 'help': 'Show help for current screen'},
    'q': {'label': 'Quit', 'help': 'Return to main menu'},
    '0': {'label': 'Exit', 'help': 'Exit the application'},
}


class MenuSystem:
    """Handles menu display and navigation"""
    
    def __init__(self, db=None):
        self.db = db
        self.navigation_stack = ['Main Menu']
    
    def get_valid_choices(self):
        """Get all valid menu choices"""
        choices = list(ALL_MENU_ITEMS.keys())
        choices.extend(QUICK_COMMANDS.keys())
        choices.extend(['h', '?', '0'])
        return choices
    
    def parse_input(self, user_input):
        """
        Parse user input and return action.
        
        Returns:
            tuple: (action_type, action_data)
            action_type: 'menu', 'shortcut', 'help', 'exit', 'invalid'
        """
        user_input = user_input.strip().lower()
        
        if user_input in ['h', '?']:
            return ('help', None)
        
        if user_input in ['0', 'exit', 'quit']:
            return ('exit', None)
        
        if user_input in ALL_MENU_ITEMS:
            return ('menu', ALL_MENU_ITEMS[user_input])
        
        if user_input in QUICK_COMMANDS:
            return ('shortcut', QUICK_COMMANDS[user_input])
        
        return ('invalid', user_input)
    
    def show_main_menu(self):
        """Display the grouped main menu"""
        for group_key, group in MENU_GROUPS.items():
            # Group header
            console.print(f"\n[bold blue]{group['icon']} {group['title']}[/bold blue]")
            
            # Menu items
            for item in group['items']:
                shortcut = f" [dim]({item['shortcut']})[/dim]" if item.get('shortcut') else ""
                console.print(f"   [blue]{item['key']:>2}[/blue]. {item['label']}{shortcut}")
        
        # Exit option
        console.print(f"\n   [blue] 0[/blue]. ❌ Exit")
        console.print()
    
    def show_help(self, context="main"):
        """Display help information"""
        CLIHelpers.show_header()
        console.print(Panel("❓ HELP", style="bold blue"))
        console.print()
        
        # Quick reference
        console.print("[bold]QUICK REFERENCE[/bold]\n")
        
        ref_table = Table(box=box.SIMPLE, show_header=False)
        ref_table.add_column("Command", style="blue", width=12)
        ref_table.add_column("Description", style="black")
        
        ref_table.add_row("1-18", "Menu options (enter number)")
        ref_table.add_row("h or ?", "Show this help")
        ref_table.add_row("0", "Exit application")
        
        console.print(ref_table)
        
        # Quick shortcuts
        console.print("\n[bold]QUICK SHORTCUTS[/bold]\n")
        
        shortcut_table = Table(box=box.SIMPLE, show_header=False)
        shortcut_table.add_column("Key", style="blue", width=8)
        shortcut_table.add_column("Action", style="black", width=25)
        shortcut_table.add_column("Description", style="dim")
        
        for key, item in sorted(QUICK_COMMANDS.items()):
            shortcut_table.add_row(key, item['label'], item.get('help', ''))
        
        console.print(shortcut_table)
        
        # All menu items
        console.print("\n[bold]ALL MENU OPTIONS[/bold]\n")
        
        for group_key, group in MENU_GROUPS.items():
            console.print(f"[bold blue]{group['icon']} {group['title']}[/bold blue]")
            
            for item in group['items']:
                console.print(f"   {item['key']:>2}. {item['label']}: [dim]{item.get('help', '')}[/dim]")
            console.print()
        
        CLIHelpers.wait_for_input()
    
    def show_contextual_status(self, db):
        """Show contextual status based on recent activity"""
        if not db:
            return
        
        try:
            stats = db.get_fraud_statistics()
            effectiveness = db.get_effectiveness_metrics()
            billing = db.get_high_risk_billing_summary()
            
            # Build status items
            status_items = []
            
            # Pending reviews
            pending_high = stats.get('high_risk', 0) - effectiveness.get('reviewed_high', 0)
            if pending_high > 0:
                status_items.append(f"⚠️  {pending_high} high-risk pending review")
            
            # Billing clusters
            if billing.get('shared_billing_clusters', 0) > 0:
                status_items.append(f"💳 {billing['shared_billing_clusters']} billing clusters detected")
            
            # Revenue at risk
            if stats.get('revenue_at_risk', 0) > 0:
                status_items.append(f"💰 ${stats['revenue_at_risk']:,.0f} revenue at risk")
            
            # Last analysis
            if stats.get('last_analysis'):
                from datetime import datetime
                try:
                    last = datetime.fromisoformat(stats['last_analysis'])
                    diff = datetime.now() - last
                    if diff.days > 0:
                        status_items.append(f"📅 Last analysis: {diff.days}d ago")
                    elif diff.seconds > 3600:
                        status_items.append(f"📅 Last analysis: {diff.seconds // 3600}h ago")
                except:
                    pass
            
            # Display status box
            if status_items:
                status_text = "\n".join(status_items)
                console.print(Panel(
                    status_text,
                    title="Recent Activity",
                    border_style="green",
                    box=box.ROUNDED
                ))
                console.print()
        
        except Exception:
            # Silently fail - status is optional
            pass
    
    def push_navigation(self, screen_name):
        """Add screen to navigation stack"""
        self.navigation_stack.append(screen_name)
    
    def pop_navigation(self):
        """Remove last screen from navigation stack"""
        if len(self.navigation_stack) > 1:
            return self.navigation_stack.pop()
        return None
    
    def show_breadcrumb(self):
        """Display current navigation breadcrumb"""
        if len(self.navigation_stack) > 1:
            CLIHelpers.show_breadcrumb(self.navigation_stack)
    
    def reset_navigation(self):
        """Reset navigation to main menu"""
        self.navigation_stack = ['Main Menu']


def create_submenu_prompt(title, options, allow_back=True):
    """
    Create a standard submenu prompt.
    
    Args:
        title: Submenu title
        options: List of dicts with 'key', 'label', and optionally 'help'
        allow_back: Whether to show back option
    
    Returns:
        Selected key or 'back' or None
    """
    console.print(f"[bold black]{title}[/bold black]\n")
    
    for opt in options:
        help_text = f" [dim]- {opt['help']}[/dim]" if opt.get('help') else ""
        console.print(f"   [{opt['key']}] {opt['label']}{help_text}")
    
    if allow_back:
        console.print(f"   [b] Back")
    
    valid_choices = [opt['key'] for opt in options]
    if allow_back:
        valid_choices.extend(['b', 'B'])
    
    choice = CLIHelpers.prompt("Choice", choices=valid_choices)
    
    if choice.lower() == 'b':
        return 'back'
    
    return choice
