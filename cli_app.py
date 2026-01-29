#!/usr/bin/env python3
"""
Fraud Detection CLI Application v3.0

A modern, modular CLI with:
- Grouped menu structure
- Quick command shortcuts
- Contextual status display
- Help system
- Responsive layouts
"""

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
import logging
import warnings

# Suppress OpenSSL/urllib3 warnings
warnings.filterwarnings('ignore', message='.*OpenSSL.*')

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Try to import rich
try:
    from rich.prompt import Prompt, Confirm, IntPrompt
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich.table import Table
    from rich.panel import Panel
    from rich import box
except ImportError:
    print("ERROR: rich library not installed")
    print("Please install it with: pip install rich")
    sys.exit(1)

# Import our modules
from cli.helpers import console, CLIHelpers
from cli.menu import MenuSystem, MENU_GROUPS, QUICK_COMMANDS, ALL_MENU_ITEMS, create_submenu_prompt
from database import Database
from api_client import APIClient
from config import Config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fraud_detection.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class FraudDetectionCLI:
    """Main CLI Application"""
    
    VERSION = "3.0"
    
    def __init__(self):
        self.config = Config()
        self.db = Database(self.config.get('database_path'))
        self.api_client = None
        self.menu = MenuSystem(self.db)
        
        # Initialize API client if key is configured
        api_key = self.config.get_api_key()
        if api_key:
            self.api_client = APIClient(api_key)
    
    def run(self):
        """Main application loop"""
        while True:
            try:
                self._show_main_screen()
                choice = self._get_user_input()
                self._handle_choice(choice)
            except KeyboardInterrupt:
                console.print("\n\n[bold yellow]Operation cancelled[/bold yellow]")
                if CLIHelpers.confirm("Exit application?", default=False):
                    self._exit()
    
    def _show_main_screen(self):
        """Display main screen with header, status, and menu"""
        CLIHelpers.show_header("FRAUD DETECTION SYSTEM", f"v{self.VERSION}")
        
        # Show contextual status
        self.menu.show_contextual_status(self.db)
        
        # Show grouped menu
        self.menu.show_main_menu()
    
    def _get_user_input(self):
        """Get and parse user input"""
        valid_choices = self.menu.get_valid_choices()
        prompt_text = "[bold black]Enter choice[/bold black] [dim](h for help)[/dim]"
        
        # Get input without strict validation to allow shortcuts
        user_input = Prompt.ask(prompt_text)
        return user_input.strip().lower()
    
    def _handle_choice(self, choice):
        """Handle user menu choice"""
        action_type, action_data = self.menu.parse_input(choice)
        
        if action_type == 'help':
            self.menu.show_help()
        
        elif action_type == 'exit':
            if CLIHelpers.confirm("Are you sure you want to exit?", default=False):
                self._exit()
        
        elif action_type in ('menu', 'shortcut'):
            method_name = action_data['method']
            if hasattr(self, method_name):
                method = getattr(self, method_name)
                self.menu.push_navigation(action_data['label'])
                try:
                    method()
                finally:
                    self.menu.pop_navigation()
            else:
                CLIHelpers.show_error(f"Feature not implemented: {method_name}")
                CLIHelpers.wait_for_input()
        
        elif action_type == 'invalid':
            CLIHelpers.show_error(f"Invalid choice: {choice}")
            CLIHelpers.show_info("Enter 'h' for help")
            CLIHelpers.wait_for_input()
    
    def _exit(self):
        """Exit the application"""
        console.print("\n[bold green]Thank you for using Fraud Detection System![/bold green]\n")
        sys.exit(0)

    # ==================== DATA MENU ====================
    
    def fetch_data_menu(self):
        """Fetch data from API"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("📥 FETCH DATA FROM API")
        
        if not self.api_client:
            CLIHelpers.show_error("API key not configured!")
            console.print("Please configure your API key in Settings")
            CLIHelpers.wait_for_input()
            return
        
        # Select data type
        choice = create_submenu_prompt("Select data type:", [
            {'key': '1', 'label': 'Leads (Free Signups)', 'help': 'Free account registrations'},
            {'key': '2', 'label': 'Sales (Paid)', 'help': 'Paid transactions'},
            {'key': '3', 'label': 'Both', 'help': 'Fetch leads and sales'},
        ])
        
        if choice == 'back':
            return
        
        data_types = {'1': ['free'], '2': ['paid'], '3': ['free', 'paid']}[choice]
        
        # Select date range
        console.print()
        choice = create_submenu_prompt("Date range:", [
            {'key': '1', 'label': 'Last 7 days'},
            {'key': '2', 'label': 'Last 30 days'},
            {'key': '3', 'label': 'Custom range'},
            {'key': '4', 'label': 'Since last fetch', 'help': 'Incremental update'},
        ])
        
        if choice == 'back':
            return
        
        end_date = datetime.now().strftime('%Y-%m-%d')
        if choice == '1':
            start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        elif choice == '2':
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        elif choice == '3':
            start_date = CLIHelpers.prompt("Start date (YYYY-MM-DD)")
            end_date = CLIHelpers.prompt("End date (YYYY-MM-DD)")
        else:
            last_date = self.db.get_last_fetch_date(data_types[0])
            start_date = last_date if last_date else (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            CLIHelpers.show_info(f"Using start date: {start_date}")
        
        # Optional filters
        filters = {}
        if CLIHelpers.confirm("Add filters?", default=False):
            filters = self._get_fetch_filters(data_types)
        
        # Execute fetch
        self._execute_fetch(data_types, start_date, end_date, filters)
    
    def _get_fetch_filters(self, data_types):
        """Get optional fetch filters from user"""
        filters = {}
        
        if CLIHelpers.confirm("Filter by POV Verified?", default=False):
            pov_choice = CLIHelpers.prompt("POV Verified status", choices=["yes", "no"])
            filters['pov_verified'] = (pov_choice == "yes")
        
        if CLIHelpers.confirm("Filter by Webmaster Code?", default=False):
            filters['webmaster_code'] = CLIHelpers.prompt("Webmaster Code")
        
        if CLIHelpers.confirm("Filter by Campaign?", default=False):
            filters['campaign'] = CLIHelpers.prompt("Campaign")
        
        return filters
    
    def _execute_fetch(self, data_types, start_date, end_date, filters):
        """Execute the data fetch operation"""
        console.print()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            
            for data_type in data_types:
                task = progress.add_task(f"Fetching {data_type} data...", total=100)
                
                try:
                    progress.update(task, advance=30)
                    data = self.api_client.fetch_data(data_type, start_date, end_date, filters)
                    progress.update(task, advance=40)
                    
                    if data:
                        if data_type == 'paid':
                            inserted, duplicates = self.db.insert_paid_records(data)
                        else:
                            inserted, duplicates = self.db.insert_free_records(data)
                        
                        progress.update(task, advance=30)
                        self.db.record_fetch(data_type, start_date, end_date, inserted)
                        
                        CLIHelpers.show_success(f"{data_type.capitalize()} fetch complete!")
                        console.print(f"   📊 Records fetched: {len(data):,}")
                        console.print(f"   💾 New records: {inserted:,}")
                        console.print(f"   ⏭️  Duplicates skipped: {duplicates:,}")
                    else:
                        progress.update(task, advance=70)
                        CLIHelpers.show_warning(f"No data returned for {data_type}")
                
                except Exception as e:
                    CLIHelpers.show_error(f"Error fetching {data_type}: {e}")
                    logger.error(f"Fetch error: {e}")
        
        CLIHelpers.wait_for_input()

    # ==================== DETECTION MENU ====================
    
    def run_fraud_detection(self):
        """Run fraud detection analysis"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("🔍 RUN FRAUD DETECTION")
        
        choice = create_submenu_prompt("Analyze:", [
            {'key': '1', 'label': 'New data only', 'help': 'Records not yet analyzed'},
            {'key': '2', 'label': 'All data', 'help': 'Re-analyze everything'},
        ])
        
        if choice == 'back':
            return
        
        # Import fraud detection script
        sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
        from email_fraud_detector import EmailFraudDetector
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            
            for data_type in ['free', 'paid']:
                task = progress.add_task(f"Analyzing {data_type} data...", total=None)
                
                # Get data
                if choice == "1":
                    df = self.db.get_unanalyzed_records(data_type)
                else:
                    import pandas as pd
                    import sqlite3
                    conn = sqlite3.connect(self.db.db_path)
                    df = pd.read_sql_query(f"SELECT * FROM {data_type}", conn)
                    conn.close()
                
                if df.empty:
                    console.print(f"[dim]No {data_type} records to analyze[/dim]")
                    continue
                
                # Initialize and run detector
                detector = EmailFraudDetector()
                df = detector.normalize_column_names(df)
                detector.build_repeated_word_map(df)
                
                # Analyze emails
                results = []
                email_col = detector.column_map.get('email')
                if not email_col:
                    CLIHelpers.show_error("Email column not found")
                    continue
                
                for idx, row in df.iterrows():
                    analysis = detector.analyze_email(row[email_col])
                    analysis['DUID'] = detector.get_column(row, 'duid', 'N/A')
                    analysis['payout_amount'] = detector.get_column(row, 'payout_amount', 0)
                    analysis['data_type'] = data_type
                    # Capture affiliate info
                    analysis['webmaster_code'] = detector.get_column(row, 'webmaster_code', None)
                    analysis['campaign'] = detector.get_column(row, 'campaign', None)
                    results.append(analysis)
                
                # Save results
                self.db.save_fraud_results(results)
                
                # Mark as analyzed
                duids = [r['DUID'] for r in results if r['DUID'] != 'N/A']
                if duids:
                    self.db.mark_as_analyzed(duids, data_type)
                
                CLIHelpers.show_success(f"Analyzed {len(results)} {data_type} records")
        
        # Show summary
        stats = self.db.get_fraud_statistics()
        self._show_analysis_summary(stats)
        CLIHelpers.wait_for_input()
    
    def _show_analysis_summary(self, stats):
        """Display analysis summary"""
        console.print()
        console.print(Panel("📊 ANALYSIS COMPLETE", style="bold green"))
        
        table = CLIHelpers.create_table([
            {'name': 'Metric', 'style': 'blue', 'width': 25},
            {'name': 'Value', 'style': 'black', 'width': 20},
        ], show_header=False)
        
        total = max(stats['total_analyzed'], 1)
        table.add_row("Total Analyzed", f"{stats['total_analyzed']:,}")
        table.add_row("🔴 High Risk (≥50)", f"{stats['high_risk']:,} ({stats['high_risk']/total*100:.1f}%)")
        table.add_row("🟡 Medium Risk (25-49)", f"{stats['medium_risk']:,} ({stats['medium_risk']/total*100:.1f}%)")
        table.add_row("💰 Revenue at Risk", CLIHelpers.format_currency(stats['revenue_at_risk']))
        
        console.print(table)
    
    def view_reports(self):
        """View fraud detection reports"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("📈 FRAUD DETECTION REPORTS")
        
        import pandas as pd
        import sqlite3
        
        conn = sqlite3.connect(self.db.db_path)
        
        # Risk distribution
        high_risk_df = pd.read_sql_query("SELECT * FROM fraud_results WHERE risk_score >= 50", conn)
        medium_risk_df = pd.read_sql_query("SELECT * FROM fraud_results WHERE risk_score >= 25 AND risk_score < 50", conn)
        low_risk_df = pd.read_sql_query("SELECT * FROM fraud_results WHERE risk_score < 25", conn)
        
        conn.close()
        
        total = len(high_risk_df) + len(medium_risk_df) + len(low_risk_df)
        
        if total == 0:
            CLIHelpers.show_warning("No fraud detection results found. Run analysis first.")
            CLIHelpers.wait_for_input()
            return
        
        console.print("[bold]Risk Distribution:[/bold]\n")
        
        table = CLIHelpers.create_table([
            {'name': 'Risk Level', 'style': 'black', 'width': 15},
            {'name': 'Count', 'style': 'black', 'width': 10, 'justify': 'right'},
            {'name': 'Percentage', 'style': 'black', 'width': 12, 'justify': 'right'},
            {'name': 'Total Payout', 'style': 'black', 'width': 15, 'justify': 'right'},
        ])
        
        table.add_row(
            "🔴 High Risk",
            f"{len(high_risk_df):,}",
            f"{len(high_risk_df)/total*100:.1f}%",
            CLIHelpers.format_currency(high_risk_df['payout_amount'].sum())
        )
        table.add_row(
            "🟡 Medium Risk",
            f"{len(medium_risk_df):,}",
            f"{len(medium_risk_df)/total*100:.1f}%",
            CLIHelpers.format_currency(medium_risk_df['payout_amount'].sum())
        )
        table.add_row(
            "🟢 Low Risk",
            f"{len(low_risk_df):,}",
            f"{len(low_risk_df)/total*100:.1f}%",
            CLIHelpers.format_currency(low_risk_df['payout_amount'].sum())
        )
        
        console.print(table)
        CLIHelpers.wait_for_input()
    
    def check_high_risk_alerts(self):
        """Check high-risk alerts"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("🚨 HIGH-RISK ALERTS")
        
        import pandas as pd
        import sqlite3
        
        conn = sqlite3.connect(self.db.db_path)
        high_risk_df = pd.read_sql_query(
            "SELECT * FROM fraud_results WHERE risk_score >= 50 ORDER BY risk_score DESC LIMIT 20",
            conn
        )
        conn.close()
        
        if high_risk_df.empty:
            CLIHelpers.show_success("No high-risk accounts found")
            CLIHelpers.wait_for_input()
            return
        
        console.print(f"[bold red]🔔 {len(high_risk_df)} HIGH RISK ACCOUNTS[/bold red]\n")
        
        # Responsive columns
        columns = [
            {'name': '#', 'style': 'blue', 'width': 3, 'priority': 1},
            {'name': 'Email', 'style': 'black', 'width': 35, 'priority': 1},
            {'name': 'DUID', 'style': 'black', 'width': 12, 'priority': 2},
            {'name': 'Risk', 'style': 'red', 'width': 6, 'justify': 'right', 'priority': 1},
            {'name': 'Payout', 'style': 'black', 'width': 10, 'justify': 'right', 'priority': 1},
            {'name': 'Flags', 'style': 'dim', 'width': 30, 'priority': 3},
        ]
        
        table = CLIHelpers.create_table(columns)
        
        for i, (idx, row) in enumerate(high_risk_df.iterrows(), start=1):
            table.add_row(
                str(i),
                CLIHelpers.truncate(row['email'], 33),
                str(row['duid']),
                str(row['risk_score']),
                CLIHelpers.format_currency(row['payout_amount']),
                CLIHelpers.truncate(str(row.get('flags', '')), 28)
            )
        
        console.print(table)
        CLIHelpers.wait_for_input()
    
    def test_single_email(self):
        """Test single email analysis"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("🧪 TEST SINGLE EMAIL")
        
        email = CLIHelpers.prompt("Enter email address")
        
        sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
        from email_fraud_detector import EmailFraudDetector
        
        console.print("\n[dim]Analyzing...[/dim]\n")
        
        detector = EmailFraudDetector()
        analysis = detector.analyze_email(email)
        
        # Display results
        table = CLIHelpers.create_table([
            {'name': 'Field', 'style': 'blue', 'width': 15},
            {'name': 'Value', 'style': 'black', 'width': 50},
        ], show_header=False)
        
        table.add_row("Email", analysis['email'])
        table.add_row("Risk Score", CLIHelpers.format_risk_score(analysis['risk_score']))
        
        risk_level = "🔴 HIGH RISK" if analysis['risk_score'] >= 50 else "🟡 MEDIUM RISK" if analysis['risk_score'] >= 25 else "🟢 LOW RISK"
        table.add_row("Risk Level", risk_level)
        
        if analysis['flags']:
            table.add_row("Flags", ", ".join(analysis['flags']))
        
        console.print(table)
        
        if CLIHelpers.confirm("\nTest another email?", default=False):
            self.test_single_email()
        else:
            CLIHelpers.wait_for_input()

    # ==================== ADVANCED ANALYSIS ====================
    
    def affiliate_analysis(self):
        """Analyze fraud by affiliate/webmaster"""
        while True:
            CLIHelpers.show_header()
            self.menu.show_breadcrumb()
            CLIHelpers.show_section("👥 AFFILIATE ANALYSIS")
            
            choice = create_submenu_prompt("Options:", [
                {'key': '1', 'label': 'Fraud by Affiliate', 'help': 'Ranked list of affiliates by fraud'},
                {'key': '2', 'label': 'View Specific Affiliate', 'help': 'Drill into one affiliate'},
                {'key': '3', 'label': 'Cross-Affiliate Patterns', 'help': 'Patterns across multiple affiliates'},
                {'key': '4', 'label': 'Export Affiliate Report', 'help': 'Export to CSV'},
            ])
            
            if choice == 'back':
                return
            
            if choice == '1':
                self._fraud_by_affiliate()
            elif choice == '2':
                self._view_specific_affiliate()
            elif choice == '3':
                self._cross_affiliate_patterns()
            elif choice == '4':
                self._export_affiliate_report()
    
    def _fraud_by_affiliate(self):
        """Show fraud statistics by affiliate"""
        df = self.db.get_affiliate_fraud_stats()
        
        if df.empty:
            CLIHelpers.show_warning("No affiliate data found.")
            console.print("[dim]Run fraud analysis first, or fetch data with affiliate info.[/dim]")
            CLIHelpers.wait_for_input()
            return
        
        console.print(f"\n[bold]Fraud by Affiliate ({len(df)} affiliates)[/bold]\n")
        
        # Sort options
        console.print("[dim]Sorted by high-risk count (descending)[/dim]\n")
        
        columns = [
            {'name': 'Affiliate', 'style': 'blue', 'width': 15, 'priority': 1},
            {'name': 'Total', 'style': 'black', 'width': 8, 'justify': 'right', 'priority': 1},
            {'name': 'High', 'style': 'red', 'width': 6, 'justify': 'right', 'priority': 1},
            {'name': 'Med', 'style': 'yellow', 'width': 6, 'justify': 'right', 'priority': 2},
            {'name': 'Low', 'style': 'green', 'width': 6, 'justify': 'right', 'priority': 3},
            {'name': 'High %', 'style': 'red', 'width': 8, 'justify': 'right', 'priority': 1},
            {'name': 'Avg Risk', 'style': 'black', 'width': 8, 'justify': 'right', 'priority': 2},
            {'name': 'HR Payout', 'style': 'red', 'width': 12, 'justify': 'right', 'priority': 1},
        ]
        
        table = CLIHelpers.create_table(columns)
        
        for _, row in df.head(20).iterrows():
            table.add_row(
                CLIHelpers.truncate(str(row['webmaster_code']), 13),
                f"{int(row['total_accounts']):,}",
                f"{int(row['high_risk_count']):,}",
                f"{int(row['medium_risk_count']):,}",
                f"{int(row['low_risk_count']):,}",
                f"{row['high_risk_pct']:.1f}%",
                f"{row['avg_risk_score']:.0f}",
                CLIHelpers.format_currency(row['high_risk_payout'])
            )
        
        console.print(table)
        
        # Summary
        total_high = df['high_risk_count'].sum()
        total_payout = df['high_risk_payout'].sum()
        console.print(f"\n[bold]Total:[/bold] {total_high:,} high-risk accounts | {CLIHelpers.format_currency(total_payout)} at risk")
        
        CLIHelpers.wait_for_input()
    
    def _view_specific_affiliate(self):
        """View fraud details for a specific affiliate"""
        webmaster_code = CLIHelpers.prompt("Enter webmaster code")
        
        df = self.db.get_fraud_by_affiliate(webmaster_code, limit=50)
        
        if df.empty:
            CLIHelpers.show_warning(f"No fraud results found for affiliate: {webmaster_code}")
            CLIHelpers.wait_for_input()
            return
        
        # Summary stats
        high_risk = len(df[df['risk_score'] >= 50])
        medium_risk = len(df[(df['risk_score'] >= 25) & (df['risk_score'] < 50)])
        total_payout = df['payout_amount'].sum()
        
        console.print(f"\n[bold]Affiliate: {webmaster_code}[/bold]")
        console.print(f"Total accounts: {len(df)} | High risk: {high_risk} | Medium risk: {medium_risk}")
        console.print(f"Total payout: {CLIHelpers.format_currency(total_payout)}\n")
        
        # Show high-risk accounts
        high_risk_df = df[df['risk_score'] >= 50].head(15)
        
        if not high_risk_df.empty:
            console.print("[bold red]High-Risk Accounts:[/bold red]\n")
            
            columns = [
                {'name': 'Email', 'style': 'black', 'width': 35, 'priority': 1},
                {'name': 'Risk', 'style': 'red', 'width': 6, 'justify': 'right', 'priority': 1},
                {'name': 'Payout', 'style': 'black', 'width': 12, 'justify': 'right', 'priority': 1},
                {'name': 'DUID', 'style': 'dim', 'width': 12, 'priority': 2},
            ]
            
            table = CLIHelpers.create_table(columns)
            
            for _, row in high_risk_df.iterrows():
                table.add_row(
                    CLIHelpers.truncate(str(row['email']), 33),
                    str(row['risk_score']),
                    CLIHelpers.format_currency(row['payout_amount']),
                    str(row['duid'])
                )
            
            console.print(table)
        
        CLIHelpers.wait_for_input()
    
    def _cross_affiliate_patterns(self):
        """Find patterns that appear across multiple affiliates"""
        CLIHelpers.show_info("Analyzing cross-affiliate patterns...")
        
        patterns = self.db.get_cross_affiliate_patterns()
        
        # Cross-affiliate domains
        domains = patterns.get('cross_affiliate_domains', [])
        if domains:
            console.print("\n[bold]Email Domains Appearing with Multiple Affiliates:[/bold]")
            console.print("[dim]These may indicate platform-wide fraud or shared fraud operations[/dim]\n")
            
            columns = [
                {'name': 'Domain', 'style': 'blue', 'width': 25, 'priority': 1},
                {'name': 'Affiliates', 'style': 'red', 'width': 10, 'justify': 'right', 'priority': 1},
                {'name': 'Accounts', 'style': 'black', 'width': 10, 'justify': 'right', 'priority': 1},
                {'name': 'Avg Risk', 'style': 'black', 'width': 10, 'justify': 'right', 'priority': 1},
            ]
            
            table = CLIHelpers.create_table(columns)
            
            for d in domains[:15]:
                table.add_row(
                    CLIHelpers.truncate(d['domain'], 23),
                    str(d['affiliates']),
                    str(d['accounts']),
                    f"{d['avg_risk']:.0f}"
                )
            
            console.print(table)
        else:
            console.print("\n[dim]No cross-affiliate domain patterns found[/dim]")
        
        # Cross-affiliate IPs
        ips = patterns.get('cross_affiliate_ips', [])
        if ips:
            console.print("\n[bold]IPs Used by Multiple Affiliates:[/bold]")
            console.print("[dim]Same IP sending traffic through different affiliates[/dim]\n")
            
            columns = [
                {'name': 'IP Address', 'style': 'blue', 'width': 18, 'priority': 1},
                {'name': 'Affiliates', 'style': 'red', 'width': 10, 'justify': 'right', 'priority': 1},
                {'name': 'Accounts', 'style': 'black', 'width': 10, 'justify': 'right', 'priority': 1},
            ]
            
            table = CLIHelpers.create_table(columns)
            
            for ip in ips[:15]:
                table.add_row(
                    str(ip['ip']),
                    str(ip['affiliates']),
                    str(ip['accounts'])
                )
            
            console.print(table)
        else:
            console.print("\n[dim]No cross-affiliate IP patterns found[/dim]")
        
        CLIHelpers.wait_for_input()
    
    def _export_affiliate_report(self):
        """Export affiliate fraud report to CSV"""
        df = self.db.get_affiliate_fraud_stats()
        
        if df.empty:
            CLIHelpers.show_warning("No affiliate data to export")
            CLIHelpers.wait_for_input()
            return
        
        from pathlib import Path
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = reports_dir / f"affiliate_fraud_report_{timestamp}.csv"
        
        df.to_csv(filename, index=False)
        CLIHelpers.show_success(f"Exported to {filename}")
        CLIHelpers.wait_for_input()
    
    def temporal_analysis(self):
        """Temporal analysis - imported from original CLI"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("🔬 TEMPORAL ANALYSIS")
        
        df = self.db.get_fraud_results()
        
        if df.empty:
            CLIHelpers.show_error("No fraud results found!")
            console.print("Please run fraud detection first.")
            CLIHelpers.wait_for_input()
            return
        
        if 'analyzed_at' not in df.columns:
            CLIHelpers.show_warning("No date information available")
            CLIHelpers.wait_for_input()
            return
        
        import pandas as pd
        df['analyzed_at'] = pd.to_datetime(df['analyzed_at'])
        df = df.sort_values('analyzed_at')
        
        CLIHelpers.show_success(f"Loaded {len(df):,} records")
        
        # Daily trends
        console.print("\n[bold]Daily Fraud Trends (Last 14 Days):[/bold]\n")
        
        daily_stats = df.groupby(df['analyzed_at'].dt.date).agg({
            'duid': 'count',
            'risk_score': 'mean',
            'payout_amount': 'sum'
        }).rename(columns={'duid': 'count', 'risk_score': 'avg_risk', 'payout_amount': 'total_payout'})
        
        table = CLIHelpers.create_table([
            {'name': 'Date', 'style': 'blue', 'width': 12},
            {'name': 'Accounts', 'style': 'black', 'width': 10, 'justify': 'right'},
            {'name': 'Avg Risk', 'style': 'black', 'width': 10, 'justify': 'right'},
            {'name': 'Total Payout', 'style': 'black', 'width': 15, 'justify': 'right'},
        ])
        
        for date, row in daily_stats.tail(14).iterrows():
            table.add_row(
                str(date),
                f"{int(row['count']):,}",
                f"{row['avg_risk']:.1f}",
                CLIHelpers.format_currency(row['total_payout'])
            )
        
        console.print(table)
        CLIHelpers.wait_for_input()
    
    def pattern_discovery(self):
        """Pattern discovery analysis"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("🔎 PATTERN DISCOVERY")
        
        choice = create_submenu_prompt("Select analysis scope:", [
            {'key': '1', 'label': 'All Data'},
            {'key': '2', 'label': 'High Risk Only (≥50)'},
            {'key': '3', 'label': 'Medium+ Risk (≥25)'},
        ])
        
        if choice == 'back':
            return
        
        min_risk = None
        if choice == '2':
            min_risk = 50
        elif choice == '3':
            min_risk = 25
        
        df = self.db.get_fraud_results(min_risk=min_risk)
        
        if df.empty:
            CLIHelpers.show_error("No data found for selected scope")
            CLIHelpers.wait_for_input()
            return
        
        CLIHelpers.show_success(f"Loaded {len(df):,} records")
        
        # Flag frequency
        import json
        flag_counts = {}
        for flags_str in df['flags'].fillna('[]'):
            try:
                flags = json.loads(flags_str) if isinstance(flags_str, str) else flags_str
                for flag in flags:
                    flag_counts[flag] = flag_counts.get(flag, 0) + 1
            except:
                continue
        
        if flag_counts:
            console.print("\n[bold]Flag Frequency:[/bold]\n")
            
            table = CLIHelpers.create_table([
                {'name': 'Flag', 'style': 'blue', 'width': 30},
                {'name': 'Count', 'style': 'black', 'width': 10, 'justify': 'right'},
                {'name': '% of Records', 'style': 'black', 'width': 12, 'justify': 'right'},
            ])
            
            for flag, count in sorted(flag_counts.items(), key=lambda x: x[1], reverse=True):
                pct = count / len(df) * 100
                table.add_row(flag, f"{count:,}", f"{pct:.1f}%")
            
            console.print(table)
        
        CLIHelpers.wait_for_input()
    
    def cluster_analysis(self):
        """Cluster analysis"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("📊 CLUSTER ANALYSIS")
        
        df = self.db.get_fraud_results()
        
        if df.empty:
            CLIHelpers.show_error("No fraud results found!")
            CLIHelpers.wait_for_input()
            return
        
        CLIHelpers.show_success(f"Loaded {len(df):,} records")
        
        # IP clustering
        if 'ip' in df.columns:
            console.print("\n[bold]Top IP Clusters:[/bold]\n")
            ip_counts = df['ip'].value_counts()
            ip_clusters = ip_counts[ip_counts > 1].head(10)
            
            if len(ip_clusters) > 0:
                table = CLIHelpers.create_table([
                    {'name': 'IP Address', 'style': 'blue', 'width': 18},
                    {'name': 'Accounts', 'style': 'black', 'width': 10, 'justify': 'right'},
                    {'name': 'Avg Risk', 'style': 'black', 'width': 10, 'justify': 'right'},
                    {'name': 'Total Payout', 'style': 'black', 'width': 15, 'justify': 'right'},
                ])
                
                for ip, count in ip_clusters.items():
                    ip_df = df[df['ip'] == ip]
                    table.add_row(
                        str(ip),
                        f"{count:,}",
                        f"{ip_df['risk_score'].mean():.1f}",
                        CLIHelpers.format_currency(ip_df['payout_amount'].sum())
                    )
                
                console.print(table)
            else:
                CLIHelpers.show_info("No IP clusters found (all unique IPs)")
        
        CLIHelpers.wait_for_input()
    
    def ensemble_anomaly_detection(self):
        """Ensemble anomaly detection"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("🎯 ANOMALY DETECTION")
        
        try:
            from pattern_detector import AnomalyDetector, PYOD_AVAILABLE
        except ImportError:
            CLIHelpers.show_error("Pattern detector module not found")
            CLIHelpers.wait_for_input()
            return
        
        if not PYOD_AVAILABLE:
            CLIHelpers.show_error("PyOD library not installed")
            console.print("Install with: pip install pyod")
            CLIHelpers.wait_for_input()
            return
        
        df = self.db.get_fraud_results()
        
        if df.empty or len(df) < 10:
            CLIHelpers.show_error(f"Insufficient data ({len(df)} records). Need at least 10.")
            CLIHelpers.wait_for_input()
            return
        
        CLIHelpers.show_info("Running anomaly detection algorithms...")
        
        try:
            detector = AnomalyDetector(contamination=0.1)
            results = detector.fit_predict(df)
        except Exception as e:
            CLIHelpers.show_error(f"Error: {e}")
            CLIHelpers.wait_for_input()
            return
        
        if not results:
            CLIHelpers.show_error("Anomaly detection failed")
            CLIHelpers.wait_for_input()
            return
        
        console.print("\n[bold]Anomaly Detection Results:[/bold]\n")
        
        table = CLIHelpers.create_table([
            {'name': 'Algorithm', 'style': 'blue', 'width': 20},
            {'name': 'Anomalies', 'style': 'black', 'width': 15, 'justify': 'right'},
            {'name': '% of Total', 'style': 'black', 'width': 12, 'justify': 'right'},
        ])
        
        for name, result in results.items():
            if name == 'consensus':
                continue
            anomaly_count = result.get('anomaly_count', 0)
            pct = anomaly_count / len(df) * 100
            table.add_row(name, f"{anomaly_count:,}", f"{pct:.1f}%")
        
        if 'consensus' in results:
            table.add_row(
                "[bold]CONSENSUS[/bold]",
                f"[bold]{results['consensus']['anomaly_count']:,}[/bold]",
                f"[bold]{results['consensus']['anomaly_count']/len(df)*100:.1f}%[/bold]"
            )
        
        console.print(table)
        CLIHelpers.wait_for_input()
    
    def drift_monitoring(self):
        """Drift monitoring"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("📉 DRIFT MONITORING")
        
        try:
            from pattern_detector import DriftDetector, ALIBI_AVAILABLE
        except ImportError:
            CLIHelpers.show_error("Pattern detector module not found")
            CLIHelpers.wait_for_input()
            return
        
        if not ALIBI_AVAILABLE:
            CLIHelpers.show_error("Alibi Detect library not installed")
            console.print("Install with: pip install alibi-detect")
            CLIHelpers.wait_for_input()
            return
        
        CLIHelpers.show_info("Drift monitoring requires sufficient historical data")
        CLIHelpers.show_info("This feature detects when fraud patterns change over time")
        CLIHelpers.wait_for_input()
    
    def billing_correlation_analysis(self):
        """Billing correlation analysis"""
        while True:
            CLIHelpers.show_header()
            self.menu.show_breadcrumb()
            CLIHelpers.show_section("💳 BILLING CORRELATION ANALYSIS")
            
            choice = create_submenu_prompt("Options:", [
                {'key': '1', 'label': 'Summary Dashboard', 'help': 'Overview of billing fraud indicators'},
                {'key': '2', 'label': 'Shared Billing Accounts', 'help': 'Same card, multiple accounts'},
                {'key': '3', 'label': 'Multi-Card IPs', 'help': 'IPs using multiple cards'},
                {'key': '4', 'label': 'Name Clusters', 'help': 'Same name, multiple accounts'},
            ])
            
            if choice == 'back':
                return
            
            if choice == '1':
                self._billing_summary()
            elif choice == '2':
                self._shared_billing_accounts()
            elif choice == '3':
                self._multi_card_ips()
            elif choice == '4':
                self._name_clusters()
    
    def _billing_summary(self):
        """Display billing correlation summary"""
        summary = self.db.get_high_risk_billing_summary()
        
        console.print("\n[bold]Billing Fraud Indicators:[/bold]\n")
        
        table = CLIHelpers.create_table([
            {'name': 'Indicator', 'style': 'blue', 'width': 30},
            {'name': 'Count', 'style': 'black', 'width': 10, 'justify': 'right'},
            {'name': 'Risk', 'style': 'black', 'width': 12},
        ], show_header=False)
        
        def risk_level(value, high_thresh, med_thresh):
            if value > high_thresh:
                return "🔴 HIGH"
            elif value > med_thresh:
                return "🟡 MEDIUM"
            return "🟢 LOW"
        
        table.add_row(
            "Shared Billing Clusters",
            str(summary['shared_billing_clusters']),
            risk_level(summary['shared_billing_clusters'], 5, 0)
        )
        table.add_row(
            "  → Accounts in Clusters",
            str(summary['accounts_in_clusters']),
            ""
        )
        table.add_row(
            "  → Payout at Risk",
            CLIHelpers.format_currency(summary['total_payout_at_risk']),
            ""
        )
        table.add_row(
            "IPs with Multiple Cards",
            str(summary['multi_card_ips']),
            risk_level(summary['multi_card_ips'], 3, 0)
        )
        table.add_row(
            "Name Clusters",
            str(summary['name_clusters']),
            risk_level(summary['name_clusters'], 5, 0)
        )
        
        console.print(table)
        CLIHelpers.wait_for_input()
    
    def _shared_billing_accounts(self):
        """Find shared billing accounts"""
        min_accounts = CLIHelpers.prompt_int("Minimum accounts per billing ID", default=2)
        df = self.db.get_billing_correlations(min_accounts=min_accounts)
        
        if df.empty:
            CLIHelpers.show_success("No shared billing accounts found")
        else:
            CLIHelpers.show_warning(f"Found {len(df)} billing IDs shared by multiple accounts!")
            
            console.print()
            table = CLIHelpers.create_table([
                {'name': 'Billing ID', 'style': 'black', 'width': 20},
                {'name': 'Accounts', 'style': 'black', 'width': 10, 'justify': 'right'},
                {'name': 'Total Payout', 'style': 'black', 'width': 15, 'justify': 'right'},
            ])
            
            for _, row in df.head(15).iterrows():
                table.add_row(
                    CLIHelpers.truncate(str(row['processor_subscriber_id']), 18),
                    str(row['account_count']),
                    CLIHelpers.format_currency(row['total_payout'])
                )
            
            console.print(table)
        
        CLIHelpers.wait_for_input()
    
    def _multi_card_ips(self):
        """Find IPs with multiple cards"""
        df = self.db.get_ip_billing_correlations()
        
        if df.empty:
            CLIHelpers.show_success("No IPs with multiple cards found")
        else:
            CLIHelpers.show_warning(f"Found {len(df)} IPs used with multiple cards!")
            
            console.print()
            table = CLIHelpers.create_table([
                {'name': 'IP Address', 'style': 'black', 'width': 18},
                {'name': 'Unique Cards', 'style': 'black', 'width': 12, 'justify': 'right'},
                {'name': 'Total Payout', 'style': 'black', 'width': 15, 'justify': 'right'},
            ])
            
            for _, row in df.head(15).iterrows():
                table.add_row(
                    str(row['ip']),
                    str(row['unique_cards']),
                    CLIHelpers.format_currency(row['total_payout'])
                )
            
            console.print(table)
        
        CLIHelpers.wait_for_input()
    
    def _name_clusters(self):
        """Find name clusters"""
        min_accounts = CLIHelpers.prompt_int("Minimum accounts per name", default=3)
        df = self.db.get_name_correlations(min_accounts=min_accounts)
        
        if df.empty:
            CLIHelpers.show_success("No name clusters found")
        else:
            console.print(f"\n[yellow]Found {len(df)} names used by multiple accounts[/yellow]\n")
            
            table = CLIHelpers.create_table([
                {'name': 'Name', 'style': 'black', 'width': 25},
                {'name': 'Accounts', 'style': 'black', 'width': 10, 'justify': 'right'},
                {'name': 'Unique Cards', 'style': 'black', 'width': 12, 'justify': 'right'},
            ])
            
            for _, row in df.head(15).iterrows():
                table.add_row(
                    str(row['full_name']).title(),
                    str(row['account_count']),
                    str(row['unique_cards'])
                )
            
            console.print(table)
        
        CLIHelpers.wait_for_input()

    # ==================== REVIEW & METRICS ====================
    
    def review_outcomes(self):
        """Review and record outcomes"""
        while True:
            CLIHelpers.show_header()
            self.menu.show_breadcrumb()
            CLIHelpers.show_section("✅ REVIEW & RECORD OUTCOMES")
            
            choice = create_submenu_prompt("Options:", [
                {'key': '1', 'label': 'Review Pending High-Risk', 'help': 'Accounts awaiting review'},
                {'key': '2', 'label': 'Record by DUID', 'help': 'Record outcome for specific account'},
                {'key': '3', 'label': 'View Recent Outcomes', 'help': 'See recently recorded outcomes'},
                {'key': '4', 'label': 'Bulk Record', 'help': 'Record multiple outcomes at once'},
            ])
            
            if choice == 'back':
                return
            
            if choice == '1':
                self._review_pending()
            elif choice == '2':
                self._record_by_duid()
            elif choice == '3':
                self._view_recent_outcomes()
            elif choice == '4':
                self._bulk_record()
    
    def _review_pending(self):
        """Review pending high-risk accounts"""
        pending_df = self.db.get_pending_reviews(min_risk=50, limit=20)
        
        if pending_df.empty:
            CLIHelpers.show_success("No pending accounts to review!")
            CLIHelpers.wait_for_input()
            return
        
        console.print(f"\n[yellow]Found {len(pending_df)} accounts pending review[/yellow]\n")
        
        table = CLIHelpers.create_table([
            {'name': '#', 'style': 'blue', 'width': 3},
            {'name': 'Email', 'style': 'black', 'width': 35},
            {'name': 'Risk', 'style': 'red', 'width': 6, 'justify': 'right'},
            {'name': 'Payout', 'style': 'black', 'width': 12, 'justify': 'right'},
        ])
        
        for i, (_, row) in enumerate(pending_df.iterrows(), start=1):
            table.add_row(
                str(i),
                CLIHelpers.truncate(row['email'], 33),
                str(row['risk_score']),
                CLIHelpers.format_currency(row['payout_amount'])
            )
        
        console.print(table)
        
        selection = CLIHelpers.prompt("\nEnter # to review (or b to go back)")
        if selection.lower() == 'b':
            return
        
        try:
            idx = int(selection) - 1
            if 0 <= idx < len(pending_df):
                self._record_outcome_for_row(pending_df.iloc[idx])
        except ValueError:
            CLIHelpers.show_error("Invalid selection")
        
        CLIHelpers.wait_for_input()
    
    def _record_by_duid(self):
        """Record outcome for specific DUID"""
        duid = CLIHelpers.prompt("Enter DUID")
        
        import pandas as pd
        import sqlite3
        
        conn = sqlite3.connect(self.db.db_path)
        df = pd.read_sql_query("SELECT * FROM fraud_results WHERE duid = ?", conn, params=[duid])
        conn.close()
        
        if df.empty:
            CLIHelpers.show_error(f"No fraud result found for DUID: {duid}")
        else:
            self._record_outcome_for_row(df.iloc[0])
        
        CLIHelpers.wait_for_input()
    
    def _record_outcome_for_row(self, row):
        """Record outcome for a single row"""
        console.print(f"\n[bold]Recording outcome for:[/bold] {row['email']}")
        console.print(f"Risk Score: {row['risk_score']} | Payout: {CLIHelpers.format_currency(row['payout_amount'])}")
        
        choice = create_submenu_prompt("\nOutcome:", [
            {'key': '1', 'label': 'Confirmed Fraud'},
            {'key': '2', 'label': 'False Positive (Legitimate)'},
            {'key': '3', 'label': 'Under Review'},
        ])
        
        if choice == 'back':
            return
        
        outcome_map = {'1': 'confirmed_fraud', '2': 'false_positive', '3': 'under_review'}
        outcome = outcome_map[choice]
        
        notes = CLIHelpers.prompt("Notes (optional)", default="")
        
        success = self.db.record_fraud_outcome(
            duid=row['duid'],
            outcome=outcome,
            notes=notes if notes else None
        )
        
        if success:
            CLIHelpers.show_success(f"Recorded: {outcome}")
        else:
            CLIHelpers.show_error("Failed to record outcome")
    
    def _view_recent_outcomes(self):
        """View recent outcomes"""
        days = CLIHelpers.prompt_int("Days to look back", default=30)
        df = self.db.get_reviewed_outcomes(days=days)
        
        if df.empty:
            CLIHelpers.show_info("No outcomes recorded in this period")
            CLIHelpers.wait_for_input()
            return
        
        summary = df['outcome'].value_counts()
        console.print("\n[bold]Outcome Summary:[/bold]\n")
        
        for outcome in ['confirmed_fraud', 'false_positive', 'under_review']:
            count = summary.get(outcome, 0)
            console.print(f"  {outcome.replace('_', ' ').title()}: {count}")
        
        CLIHelpers.wait_for_input()
    
    def _bulk_record(self):
        """Bulk record outcomes"""
        choice = create_submenu_prompt("Select outcome to apply:", [
            {'key': '1', 'label': 'Confirmed Fraud'},
            {'key': '2', 'label': 'False Positive'},
            {'key': '3', 'label': 'Under Review'},
        ])
        
        if choice == 'back':
            return
        
        outcome_map = {'1': 'confirmed_fraud', '2': 'false_positive', '3': 'under_review'}
        outcome = outcome_map[choice]
        
        duids_input = CLIHelpers.prompt("Enter DUIDs (comma-separated)")
        duids = [d.strip() for d in duids_input.split(',') if d.strip()]
        
        if not duids:
            CLIHelpers.show_error("No valid DUIDs entered")
            CLIHelpers.wait_for_input()
            return
        
        success_count = 0
        for duid in duids:
            if self.db.record_fraud_outcome(duid=duid, outcome=outcome):
                success_count += 1
        
        CLIHelpers.show_success(f"Recorded {success_count}/{len(duids)} outcomes")
        CLIHelpers.wait_for_input()
    
    def effectiveness_dashboard(self):
        """Effectiveness dashboard"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("📊 EFFECTIVENESS DASHBOARD")
        
        self.db.calculate_and_store_metrics()
        metrics = self.db.get_effectiveness_metrics()
        
        # Overview
        console.print("[bold]Detection Overview:[/bold]\n")
        
        table = CLIHelpers.create_table([
            {'name': 'Metric', 'style': 'blue', 'width': 25},
            {'name': 'High Risk', 'style': 'red', 'width': 15, 'justify': 'right'},
            {'name': 'Medium Risk', 'style': 'yellow', 'width': 15, 'justify': 'right'},
        ], show_header=True)
        
        table.add_row("Total Flagged", f"{metrics['total_flagged_high']:,}", f"{metrics['total_flagged_medium']:,}")
        table.add_row("Reviewed", f"{metrics['reviewed_high']:,}", f"{metrics['reviewed_medium']:,}")
        table.add_row("Confirmed Fraud", f"{metrics['confirmed_fraud_high']:,}", f"{metrics['confirmed_fraud_medium']:,}")
        table.add_row("False Positives", f"{metrics['false_positives_high']:,}", f"{metrics['false_positives_medium']:,}")
        
        precision_h = CLIHelpers.format_percentage(metrics['precision_high']) if metrics['precision_high'] else "N/A"
        precision_m = CLIHelpers.format_percentage(metrics['precision_medium']) if metrics['precision_medium'] else "N/A"
        table.add_row("Precision", precision_h, precision_m)
        
        console.print(table)
        
        # Financial
        console.print("\n[bold]Financial Impact:[/bold]\n")
        console.print(f"  Payout at Risk: {CLIHelpers.format_currency(metrics['total_payout_at_risk'])}")
        console.print(f"  Confirmed Fraud: {CLIHelpers.format_currency(metrics['confirmed_fraud_amount'])}")
        console.print(f"  Recovered: {CLIHelpers.format_currency(metrics['recovery_amount'])}")
        
        # Recommendations
        console.print("\n[bold]Recommendations:[/bold]")
        
        pending = metrics['total_flagged_high'] - metrics['reviewed_high']
        if pending > 0:
            console.print(f"  ⚠️  {pending:,} high-risk accounts pending review")
        
        if metrics['reviewed_high'] < 10:
            console.print("  📝 Review more accounts to get reliable precision estimates")
        
        CLIHelpers.wait_for_input()
    
    def low_risk_sampling(self):
        """Low-risk sampling for false negative detection"""
        while True:
            CLIHelpers.show_header()
            self.menu.show_breadcrumb()
            CLIHelpers.show_section("🔍 LOW-RISK SAMPLING")
            
            console.print("[dim]Purpose: Find fraud that slipped through detection[/dim]\n")
            
            choice = create_submenu_prompt("Options:", [
                {'key': '1', 'label': 'Generate New Sample', 'help': 'Random low-risk accounts'},
                {'key': '2', 'label': 'Review Pending Samples'},
                {'key': '3', 'label': 'View Sample History'},
            ])
            
            if choice == 'back':
                return
            
            if choice == '1':
                self._generate_sample()
            elif choice == '2':
                self._review_samples()
            elif choice == '3':
                self._sample_history()
    
    def _generate_sample(self):
        """Generate low-risk sample"""
        count = CLIHelpers.prompt_int("Number to sample", default=20)
        df = self.db.sample_low_risk_accounts(count=count, max_risk=24)
        
        if df.empty:
            CLIHelpers.show_info("No unsampled low-risk accounts available")
        else:
            CLIHelpers.show_success(f"Sampled {len(df)} accounts")
            console.print("[dim]Review them to check for missed fraud[/dim]")
        
        CLIHelpers.wait_for_input()
    
    def _review_samples(self):
        """Review pending samples"""
        pending_df = self.db.get_low_risk_samples(status='pending')
        
        if pending_df.empty:
            CLIHelpers.show_info("No pending samples to review")
            CLIHelpers.wait_for_input()
            return
        
        console.print(f"\n[yellow]{len(pending_df)} samples pending[/yellow]\n")
        
        for _, row in pending_df.head(5).iterrows():
            console.print(f"  {row['email']} (Risk: {row['risk_score']})")
        
        if len(pending_df) > 5:
            console.print(f"  ... and {len(pending_df) - 5} more")
        
        CLIHelpers.wait_for_input()
    
    def _sample_history(self):
        """View sample history"""
        df = self.db.get_low_risk_samples(status='all')
        
        if df.empty:
            CLIHelpers.show_info("No samples recorded yet")
        else:
            summary = df['review_status'].value_counts()
            console.print("\n[bold]Sample Summary:[/bold]\n")
            
            for status in ['pending', 'missed_fraud', 'legitimate']:
                count = summary.get(status, 0)
                console.print(f"  {status.replace('_', ' ').title()}: {count}")
            
            # False negative rate
            reviewed = len(df[df['review_status'].isin(['missed_fraud', 'legitimate'])])
            missed = len(df[df['review_status'] == 'missed_fraud'])
            
            if reviewed > 0:
                rate = missed / reviewed * 100
                console.print(f"\n[bold]Estimated False Negative Rate: {rate:.1f}%[/bold]")
        
        CLIHelpers.wait_for_input()

    # ==================== SYSTEM ====================
    
    def view_dashboard(self):
        """View dashboard metrics"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("📊 DASHBOARD METRICS")
        
        stats = self.db.get_fraud_statistics()
        
        table = CLIHelpers.create_table([
            {'name': 'Metric', 'style': 'blue', 'width': 25},
            {'name': 'Value', 'style': 'black', 'width': 20},
        ], show_header=False)
        
        table.add_row("Total Analyzed", f"{stats['total_analyzed']:,}")
        table.add_row("High Risk Accounts", f"[red]{stats['high_risk']:,}[/red]")
        table.add_row("Medium Risk Accounts", f"[yellow]{stats['medium_risk']:,}[/yellow]")
        table.add_row("Detection Rate", f"{stats['high_risk']/max(stats['total_analyzed'],1)*100:.1f}%")
        table.add_row("Revenue at Risk", f"[red]{CLIHelpers.format_currency(stats['revenue_at_risk'])}[/red]")
        
        console.print(table)
        CLIHelpers.wait_for_input()
    
    def configure_settings(self):
        """Configure settings"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("⚙️ SETTINGS")
        
        # Show current settings
        api_key = self.config.get_api_key()
        
        console.print("[bold]Current Settings:[/bold]\n")
        console.print(f"  API Key: {'****' + api_key[-4:] if api_key else '[red]Not configured[/red]'}")
        console.print(f"  High Risk Threshold: ≥ {self.config.get_risk_threshold('high')}")
        console.print(f"  Medium Risk Threshold: {self.config.get_risk_threshold('medium')}-{self.config.get_risk_threshold('high')-1}")
        
        choice = create_submenu_prompt("\nOptions:", [
            {'key': '1', 'label': 'Set API Key'},
            {'key': '2', 'label': 'Change Risk Thresholds'},
        ])
        
        if choice == 'back':
            return
        
        if choice == '1':
            api_key = CLIHelpers.prompt("Enter API Key")
            self.config.set_api_key(api_key)
            self.api_client = APIClient(api_key)
            CLIHelpers.show_success("API Key saved")
        
        elif choice == '2':
            high = CLIHelpers.prompt_int("High risk threshold", default=50)
            medium = CLIHelpers.prompt_int("Medium risk threshold", default=25)
            self.config.set('risk_thresholds.high', high)
            self.config.set('risk_thresholds.medium', medium)
            CLIHelpers.show_success("Thresholds updated")
        
        CLIHelpers.wait_for_input()
    
    def view_logs(self):
        """View recent logs"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("📖 RECENT LOGS")
        
        log_file = 'fraud_detection.log'
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                lines = f.readlines()[-30:]
            
            for line in lines:
                console.print(line.strip())
        else:
            CLIHelpers.show_info("No log file found")
        
        CLIHelpers.wait_for_input()
    
    def export_reports(self):
        """Export reports"""
        CLIHelpers.show_header()
        self.menu.show_breadcrumb()
        CLIHelpers.show_section("📁 EXPORT REPORTS")
        
        choice = create_submenu_prompt("Export:", [
            {'key': '1', 'label': 'All Fraud Results'},
            {'key': '2', 'label': 'High Risk Only'},
            {'key': '3', 'label': 'Billing Correlations'},
        ])
        
        if choice == 'back':
            return
        
        from pathlib import Path
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if choice == '1':
            df = self.db.get_fraud_results()
            filename = reports_dir / f"fraud_results_{timestamp}.csv"
        elif choice == '2':
            df = self.db.get_fraud_results(min_risk=50)
            filename = reports_dir / f"high_risk_{timestamp}.csv"
        elif choice == '3':
            df = self.db.get_billing_correlations()
            filename = reports_dir / f"billing_correlations_{timestamp}.csv"
        
        if df.empty:
            CLIHelpers.show_info("No data to export")
        else:
            df.to_csv(filename, index=False)
            CLIHelpers.show_success(f"Exported to {filename}")
        
        CLIHelpers.wait_for_input()


def main():
    """Main entry point"""
    try:
        cli = FraudDetectionCLI()
        cli.run()
    except KeyboardInterrupt:
        console.print("\n\n[bold yellow]Goodbye![/bold yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[bold red]Fatal error: {e}[/bold red]")
        logger.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
