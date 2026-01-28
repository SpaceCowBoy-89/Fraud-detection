#!/usr/bin/env python3
"""
Rich CLI Interface for Fraud Detection System
"""
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
import logging
import warnings

# Suppress OpenSSL/urllib3 warnings
warnings.filterwarnings('ignore', message='.*OpenSSL.*')

# Try to import rich, provide installation message if not available
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich.prompt import Prompt, Confirm, IntPrompt
    from rich.layout import Layout
    from rich.live import Live
    from rich.text import Text
    from rich import box
except ImportError:
    print("ERROR: rich library not installed")
    print("Please install it with: pip install rich")
    sys.exit(1)

# Import our modules
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

# Console with theme optimized for both light and dark backgrounds
from rich.theme import Theme
custom_theme = Theme({
    "info": "black",
    "warning": "dark_orange",
    "error": "red",
    "success": "dark_green",
    "highlight": "bold blue",
    "menu": "black",
    "value": "black bold"
})
console = Console(theme=custom_theme)


class FraudDetectionCLI:
    def __init__(self):
        self.config = Config()
        self.db = Database(self.config.get('database_path'))
        self.api_client = None

        # Initialize API client if key is configured
        api_key = self.config.get_api_key()
        if api_key:
            self.api_client = APIClient(api_key)

    def show_header(self):
        """Display application header"""
        console.clear()
        header = Panel(
            Text("FRAUD DETECTION SYSTEM v2.0", style="bold black", justify="center"),
            style="blue",
            box=box.DOUBLE
        )
        console.print(header)
        console.print()

    def show_status(self):
        """Display current system status"""
        stats = self.db.get_fraud_statistics()

        status_table = Table(show_header=False, box=box.SIMPLE)
        status_table.add_column("Metric", style="blue")
        status_table.add_column("Value", style="black")

        last_fetch = stats.get('last_analysis', 'Never')
        if last_fetch and last_fetch != 'Never':
            last_fetch = datetime.fromisoformat(last_fetch).strftime('%Y-%m-%d %H:%M:%S')

        status_table.add_row("📊 Last Analysis", str(last_fetch))
        status_table.add_row("🔍 Accounts Analyzed", f"{stats.get('total_analyzed', 0):,}")
        status_table.add_row("🔴 High Risk Flagged", f"{stats.get('high_risk', 0):,} ({stats.get('high_risk', 0) / max(stats.get('total_analyzed', 1), 1) * 100:.1f}%)")
        status_table.add_row("💰 Revenue at Risk", f"${stats.get('revenue_at_risk', 0):,.2f}")

        console.print(Panel(status_table, title="Current Status", border_style="green"))
        console.print()

    def main_menu(self):
        """Display main menu"""
        while True:
            self.show_header()
            self.show_status()

            menu_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
            menu_table.add_column("Option", style="blue bold", width=4)
            menu_table.add_column("Description", style="black")

            menu_table.add_row("1", "🔄 Fetch New Data from API")
            menu_table.add_row("2", "🔍 Run Fraud Detection Analysis")
            menu_table.add_row("3", "📈 View Fraud Detection Reports")
            menu_table.add_row("4", "⚙️  Configure Settings")
            menu_table.add_row("5", "📊 View Dashboard Metrics")
            menu_table.add_row("6", "🚨 Check High-Risk Alerts")
            menu_table.add_row("7", "📁 Export Reports")
            menu_table.add_row("8", "🧪 Test Mode (Analyze Single Email)")
            menu_table.add_row("9", "📖 View Logs")
            menu_table.add_row("10", "🔬 Temporal Analysis")
            menu_table.add_row("11", "🔎 Pattern Discovery")
            menu_table.add_row("12", "📊 Cluster Analysis")
            menu_table.add_row("13", "🎯 Ensemble Anomaly Detection")
            menu_table.add_row("14", "🤖 Advanced Anomaly Detection")
            menu_table.add_row("15", "📉 Drift Monitoring")
            menu_table.add_row("0", "❌ Exit")

            console.print(Panel(menu_table, title="MAIN MENU", border_style="blue"))

            choice = Prompt.ask("\n[bold black]Enter your choice[/bold black]", choices=["0","1","2","3","4","5","6","7","8","9","10","11","12","13","14","15"])

            if choice == "1":
                self.fetch_data_menu()
            elif choice == "2":
                self.run_fraud_detection()
            elif choice == "3":
                self.view_reports()
            elif choice == "4":
                self.configure_settings()
            elif choice == "5":
                self.view_dashboard()
            elif choice == "6":
                self.check_high_risk_alerts()
            elif choice == "7":
                self.export_reports()
            elif choice == "8":
                self.test_single_email()
            elif choice == "9":
                self.view_logs()
            elif choice == "10":
                self.temporal_analysis()
            elif choice == "11":
                self.pattern_discovery()
            elif choice == "12":
                self.cluster_analysis()
            elif choice == "13":
                self.ensemble_anomaly_detection()
            elif choice == "14":
                self.advanced_anomaly_detection()
            elif choice == "15":
                self.drift_monitoring()
            elif choice == "0":
                if Confirm.ask("\n[bold yellow]Are you sure you want to exit?[/bold yellow]"):
                    console.print("\n[bold green]Thank you for using Fraud Detection System![/bold green]\n")
                    sys.exit(0)

    def fetch_data_menu(self):
        """Fetch data from API"""
        self.show_header()

        if not self.api_client:
            console.print("[bold red]❌ API key not configured![/bold red]")
            console.print("Please configure your API key in Settings (Option 4)")
            Prompt.ask("\nPress Enter to continue")
            return

        console.print(Panel("📥 FETCH DATA FROM API", style="bold blue"))
        console.print()

        # Select data type
        console.print("[bold black]Select data type to fetch:[/bold black]")
        console.print("  1. Leads (Free Signups)")
        console.print("  2. Sales (Paid Transactions)")
        console.print("  3. Both")
        data_type_choice = Prompt.ask("Choice", choices=["1", "2", "3"])

        data_types = []
        if data_type_choice == "1":
            data_types = ['free']
        elif data_type_choice == "2":
            data_types = ['paid']
        else:
            data_types = ['free', 'paid']

        # Select date range
        console.print("\n[bold black]Date Range:[/bold black]")
        console.print("  1. Last 7 days")
        console.print("  2. Last 30 days")
        console.print("  3. Custom date range")
        console.print("  4. Since last fetch (incremental)")
        date_choice = Prompt.ask("Choice", choices=["1", "2", "3", "4"])

        if date_choice == "1":
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        elif date_choice == "2":
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        elif date_choice == "3":
            start_date = Prompt.ask("Start date (YYYY-MM-DD)")
            end_date = Prompt.ask("End date (YYYY-MM-DD)")
        else:
            # Incremental - use last fetch date
            end_date = datetime.now().strftime('%Y-%m-%d')
            last_date = self.db.get_last_fetch_date(data_types[0])
            start_date = last_date if last_date else (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            console.print(f"[dim]Using start date: {start_date}[/dim]")

        # Optional filters
        filters = {}
        console.print("\n[bold black]Optional Filters:[/bold black]")

        if Confirm.ask("Filter by POV Verified?", default=False):
            pov_choice = Prompt.ask("POV Verified status", choices=["yes", "no"])
            filters['pov_verified'] = (pov_choice == "yes")

        if Confirm.ask("Filter by Site Code?", default=False):
            filters['site_code'] = Prompt.ask("Site Code")

        if Confirm.ask("Filter by User Agent?", default=False):
            filters['custom_http_user_agent'] = Prompt.ask("User Agent (partial match)")

        if 'paid' in data_types:
            if Confirm.ask("Filter by Chargeback Count?", default=False):
                filters['chargeback_count'] = IntPrompt.ask("Minimum chargeback count")

            if Confirm.ask("Filter by Credit Count?", default=False):
                filters['credit_count'] = IntPrompt.ask("Minimum credit count")

        if Confirm.ask("Filter by Webmaster Code?", default=False):
            filters['webmaster_code'] = Prompt.ask("Webmaster Code (comma separated)")

        if Confirm.ask("Filter by Email Domain?", default=False):
            filters['email_domain'] = Prompt.ask("Email Domain")

        if Confirm.ask("Filter by Campaign?", default=False):
            filters['campaign'] = Prompt.ask("Campaign")

        # Review and confirm filters
        while True:
            console.print("\n" + "="*80)
            console.print(Panel("📋 REVIEW YOUR FILTERS", style="bold blue"))
            console.print()

            # Display all applied filters
            review_table = Table(show_header=False, box=box.SIMPLE)
            review_table.add_column("Filter", style="blue", width=25)
            review_table.add_column("Value", style="black")

            review_table.add_row("Data Type", ", ".join([dt.capitalize() for dt in data_types]))
            review_table.add_row("Date Range", f"{start_date} to {end_date}")

            if filters:
                for key, value in filters.items():
                    display_key = key.replace('_', ' ').title()
                    display_value = str(value) if value is not None else "Not set"
                    review_table.add_row(display_key, display_value)
            else:
                review_table.add_row("Filters", "[dim]No filters applied[/dim]")

            console.print(review_table)
            console.print()

            console.print("[bold black]What would you like to do?[/bold black]")
            console.print("  [P] Proceed with these filters")
            console.print("  [E] Edit filters")
            console.print("  [C] Cancel and return to main menu")

            action = Prompt.ask("Choice", choices=["P", "p", "E", "e", "C", "c"])

            if action.upper() == "P":
                break  # Proceed with data fetching
            elif action.upper() == "C":
                return  # Return to main menu
            elif action.upper() == "E":
                # Edit filters
                console.print("\n[bold black]Select filter to edit:[/bold black]")
                console.print("  [1] POV Verified")
                console.print("  [2] Site Code")
                console.print("  [3] User Agent")
                if 'paid' in data_types:
                    console.print("  [4] Chargeback Count")
                    console.print("  [5] Credit Count")
                console.print("  [6] Webmaster Code")
                console.print("  [7] Email Domain")
                console.print("  [8] Campaign")
                console.print("  [9] Clear all filters")
                console.print("  [B] Back to review")

                edit_choices = ["1", "2", "3", "6", "7", "8", "9", "B", "b"]
                if 'paid' in data_types:
                    edit_choices.extend(["4", "5"])

                edit_choice = Prompt.ask("Choice", choices=edit_choices)

                if edit_choice.upper() == "B":
                    continue  # Go back to review

                elif edit_choice == "1":
                    if Confirm.ask("Enable POV Verified filter?", default='pov_verified' in filters):
                        pov_choice = Prompt.ask("POV Verified status", choices=["yes", "no"], default="yes" if filters.get('pov_verified') else "no")
                        filters['pov_verified'] = (pov_choice == "yes")
                    else:
                        filters.pop('pov_verified', None)

                elif edit_choice == "2":
                    if Confirm.ask("Enable Site Code filter?", default='site_code' in filters):
                        filters['site_code'] = Prompt.ask("Site Code", default=filters.get('site_code', ''))
                    else:
                        filters.pop('site_code', None)

                elif edit_choice == "3":
                    if Confirm.ask("Enable User Agent filter?", default='custom_http_user_agent' in filters):
                        filters['custom_http_user_agent'] = Prompt.ask("User Agent (partial match)", default=filters.get('custom_http_user_agent', ''))
                    else:
                        filters.pop('custom_http_user_agent', None)

                elif edit_choice == "4" and 'paid' in data_types:
                    if Confirm.ask("Enable Chargeback Count filter?", default='chargeback_count' in filters):
                        filters['chargeback_count'] = IntPrompt.ask("Minimum chargeback count", default=filters.get('chargeback_count', 1))
                    else:
                        filters.pop('chargeback_count', None)

                elif edit_choice == "5" and 'paid' in data_types:
                    if Confirm.ask("Enable Credit Count filter?", default='credit_count' in filters):
                        filters['credit_count'] = IntPrompt.ask("Minimum credit count", default=filters.get('credit_count', 1))
                    else:
                        filters.pop('credit_count', None)

                elif edit_choice == "6":
                    if Confirm.ask("Enable Webmaster Code filter?", default='webmaster_code' in filters):
                        filters['webmaster_code'] = Prompt.ask("Webmaster Code (comma separated)", default=filters.get('webmaster_code', ''))
                    else:
                        filters.pop('webmaster_code', None)

                elif edit_choice == "7":
                    if Confirm.ask("Enable Email Domain filter?", default='email_domain' in filters):
                        filters['email_domain'] = Prompt.ask("Email Domain", default=filters.get('email_domain', ''))
                    else:
                        filters.pop('email_domain', None)

                elif edit_choice == "8":
                    if Confirm.ask("Enable Campaign filter?", default='campaign' in filters):
                        filters['campaign'] = Prompt.ask("Campaign", default=filters.get('campaign', ''))
                    else:
                        filters.pop('campaign', None)

                elif edit_choice == "9":
                    if Confirm.ask("[bold yellow]Clear all filters?[/bold yellow]"):
                        filters.clear()
                        console.print("[green]✅ All filters cleared[/green]")

                console.print("[green]✅ Filter updated[/green]")
                # Loop back to review screen

        # Fetch data
        console.print("\n" + "="*80)

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
                    # Simulate progress (actual API call doesn't provide progress)
                    progress.update(task, advance=30)

                    data = self.api_client.fetch_data(data_type, start_date, end_date, filters)

                    progress.update(task, advance=40)

                    if data:
                        if data_type == 'paid':
                            inserted, duplicates = self.db.insert_paid_records(data)
                        else:
                            inserted, duplicates = self.db.insert_free_records(data)

                        progress.update(task, advance=30)

                        # Record fetch
                        self.db.record_fetch(data_type, start_date, end_date, inserted)

                        console.print(f"\n[green]✅ {data_type.capitalize()} fetch complete![/green]")
                        console.print(f"   📊 Records fetched: {len(data):,}")
                        console.print(f"   💾 New records stored: {inserted:,}")
                        console.print(f"   ⏭️  Duplicates skipped: {duplicates:,}")
                    else:
                        progress.update(task, advance=70)
                        console.print(f"\n[yellow]⚠️  No data returned for {data_type}[/yellow]")

                except Exception as e:
                    console.print(f"\n[red]❌ Error fetching {data_type} data: {e}[/red]")
                    logger.error(f"Fetch error: {e}")

        console.print("\n" + "="*80)
        Prompt.ask("\nPress Enter to continue")

    def run_fraud_detection(self):
        """Run fraud detection analysis"""
        self.show_header()
        console.print(Panel("🔍 RUN FRAUD DETECTION ANALYSIS", style="bold blue"))
        console.print()

        console.print("[bold black]Analyze:[/bold black]")
        console.print("  1. New data only (not yet analyzed)")
        console.print("  2. All data (re-analyze everything)")
        analyze_choice = Prompt.ask("Choice", choices=["1", "2"])

        # Import fraud detection script
        sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
        from email_fraud_detector import EmailFraudDetector

        console.print("\n" + "="*80)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:

            # Process both free and paid data
            for data_type in ['free', 'paid']:
                task = progress.add_task(f"Analyzing {data_type} data...", total=None)

                # Get data to analyze
                if analyze_choice == "1":
                    df = self.db.get_unanalyzed_records(data_type)
                else:
                    # Get all records
                    import pandas as pd
                    import sqlite3
                    conn = sqlite3.connect(self.db.db_path)
                    table = data_type
                    df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
                    conn.close()

                if df.empty:
                    console.print(f"\n[yellow]No {data_type} records to analyze[/yellow]")
                    continue

                console.print(f"\n[black]Step 1/5: Analyzing {len(df)} {data_type} records...[/black]")

                # Initialize detector
                detector = EmailFraudDetector()

                # Normalize column names
                df = detector.normalize_column_names(df)

                console.print("[green]✓ Column names normalized[/green]")

                # Build repeated word map
                console.print("[black]Step 2/5: Building repeated word patterns...[/black]")
                detector.build_repeated_word_map(df)
                console.print(f"[green]✓ Found {len(detector.repeated_words)} repeated patterns[/green]")

                # Analyze emails
                console.print("[black]Step 3/5: Analyzing individual emails...[/black]")
                results = []
                email_col = detector.column_map.get('email')

                if not email_col:
                    console.print("[red]❌ Email column not found[/red]")
                    continue

                for idx, row in df.iterrows():
                    analysis = detector.analyze_email(row[email_col])
                    analysis['DUID'] = detector.get_column(row, 'duid', 'N/A')
                    analysis['payout_amount'] = detector.get_column(row, 'payout_amount', 0)
                    analysis['data_type'] = data_type
                    results.append(analysis)

                console.print(f"[green]✓ Analyzed {len(results)} emails[/green]")

                # Save results
                console.print("[black]Step 4/5: Saving results...[/black]")
                self.db.save_fraud_results(results)

                # Mark as analyzed
                duids = [r['DUID'] for r in results if r['DUID'] != 'N/A']
                if duids:
                    self.db.mark_as_analyzed(duids, data_type)

                console.print("[green]✓ Results saved[/green]")

        # Get statistics
        stats = self.db.get_fraud_statistics()

        console.print("\n" + "="*80)
        console.print(Panel("📊 ANALYSIS COMPLETE", style="bold green"))
        console.print()

        summary_table = Table(show_header=False, box=box.SIMPLE)
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Value", style="white")

        summary_table.add_row("Total Analyzed", f"{stats['total_analyzed']:,} accounts")
        summary_table.add_row("🔴 High Risk (≥50)", f"{stats['high_risk']:,} accounts ({stats['high_risk'] / max(stats['total_analyzed'], 1) * 100:.1f}%)")
        summary_table.add_row("🟡 Medium Risk (25-49)", f"{stats['medium_risk']:,} accounts ({stats['medium_risk'] / max(stats['total_analyzed'], 1) * 100:.1f}%)")
        summary_table.add_row("💰 Revenue at Risk", f"${stats['revenue_at_risk']:,.2f}")

        console.print(summary_table)

        console.print("\n" + "="*80)
        Prompt.ask("\nPress Enter to continue")

    def view_reports(self):
        """View fraud detection reports"""
        self.show_header()
        console.print(Panel("📈 VIEW FRAUD DETECTION REPORTS", style="bold blue"))
        console.print()

        # Get reports from database
        import sqlite3
        import pandas as pd

        conn = sqlite3.connect(self.db.db_path)

        # Show summary
        console.print("[bold black]Risk Distribution:[/bold black]\n")

        summary_table = Table(box=box.ROUNDED)
        summary_table.add_column("Risk Level", style="black")
        summary_table.add_column("Count", justify="right", style="black")
        summary_table.add_column("Percentage", justify="right", style="black")
        summary_table.add_column("Total Payout", justify="right", style="black")

        # Query risk levels
        high_risk_df = pd.read_sql_query("SELECT * FROM fraud_results WHERE risk_score >= 50", conn)
        medium_risk_df = pd.read_sql_query("SELECT * FROM fraud_results WHERE risk_score >= 25 AND risk_score < 50", conn)
        low_risk_df = pd.read_sql_query("SELECT * FROM fraud_results WHERE risk_score < 25", conn)

        total = len(high_risk_df) + len(medium_risk_df) + len(low_risk_df)

        if total > 0:
            summary_table.add_row(
                "🔴 High Risk",
                f"{len(high_risk_df):,}",
                f"{len(high_risk_df)/total*100:.1f}%",
                f"${high_risk_df['payout_amount'].sum():,.2f}"
            )
            summary_table.add_row(
                "🟡 Medium Risk",
                f"{len(medium_risk_df):,}",
                f"{len(medium_risk_df)/total*100:.1f}%",
                f"${medium_risk_df['payout_amount'].sum():,.2f}"
            )
            summary_table.add_row(
                "🟢 Low Risk",
                f"{len(low_risk_df):,}",
                f"{len(low_risk_df)/total*100:.1f}%",
                f"${low_risk_df['payout_amount'].sum():,.2f}"
            )

            console.print(summary_table)
        else:
            console.print("[yellow]No fraud detection results found. Run analysis first.[/yellow]")

        conn.close()

        Prompt.ask("\nPress Enter to continue")

    def configure_settings(self):
        """Configure system settings"""
        self.show_header()
        console.print(Panel("⚙️  CONFIGURATION SETTINGS", style="bold blue"))
        console.print()

        # Show current settings
        console.print("[bold black]Current Settings:[/bold black]\n")

        settings_table = Table(show_header=False, box=box.SIMPLE)
        settings_table.add_column("Setting", style="blue")
        settings_table.add_column("Value", style="black")

        api_key = self.config.get_api_key()
        settings_table.add_row("API Key", "********" + api_key[-4:] if api_key else "[red]Not configured[/red]")
        settings_table.add_row("High Risk Threshold", f"≥ {self.config.get_risk_threshold('high')} points")
        settings_table.add_row("Medium Risk Threshold", f"{self.config.get_risk_threshold('medium')}-{self.config.get_risk_threshold('high')-1} points")

        console.print(settings_table)

        console.print("\n[bold black]Actions:[/bold black]")
        console.print("  [1] Set API Key")
        console.print("  [2] Change risk thresholds")
        console.print("  [3] View/Edit detection weights")
        console.print("  [4] Manage whitelist")
        console.print("  [5] Export configuration")
        console.print("  [6] Reset to defaults")
        console.print("  [B] Back to main menu")

        choice = Prompt.ask("Choice", choices=["1", "2", "3", "4", "5", "6", "B", "b"])

        if choice == "1":
            api_key = Prompt.ask("Enter API Key")
            self.config.set_api_key(api_key)
            self.api_client = APIClient(api_key)
            console.print("[green]✅ API Key saved[/green]")
            Prompt.ask("\nPress Enter to continue")

        elif choice == "2":
            high = IntPrompt.ask("High risk threshold", default=50)
            medium = IntPrompt.ask("Medium risk threshold", default=25)
            self.config.set('risk_thresholds.high', high)
            self.config.set('risk_thresholds.medium', medium)
            console.print("[green]✅ Thresholds updated[/green]")
            Prompt.ask("\nPress Enter to continue")

        elif choice.upper() == "B":
            return
        else:
            console.print("[yellow]Feature coming soon[/yellow]")
            Prompt.ask("\nPress Enter to continue")

    def view_dashboard(self):
        """View dashboard metrics"""
        self.show_header()
        console.print(Panel("📊 DASHBOARD METRICS", style="bold blue"))
        console.print()

        stats = self.db.get_fraud_statistics()

        # Create metrics display
        metrics_table = Table(box=box.ROUNDED, show_header=False)
        metrics_table.add_column("Metric", style="bold blue", width=30)
        metrics_table.add_column("Value", style="bold black", width=20)

        metrics_table.add_row("Total Accounts Analyzed", f"{stats['total_analyzed']:,}")
        metrics_table.add_row("High Risk Accounts", f"[red]{stats['high_risk']:,}[/red]")
        metrics_table.add_row("Medium Risk Accounts", f"[yellow]{stats['medium_risk']:,}[/yellow]")
        metrics_table.add_row("Fraud Detection Rate", f"{stats['high_risk'] / max(stats['total_analyzed'], 1) * 100:.1f}%")
        metrics_table.add_row("Revenue at Risk", f"[red]${stats['revenue_at_risk']:,.2f}[/red]")

        console.print(metrics_table)

        Prompt.ask("\nPress Enter to continue")

    def check_high_risk_alerts(self):
        """Check high-risk alerts"""
        self.show_header()
        console.print(Panel("🚨 HIGH-RISK ALERTS", style="bold red"))
        console.print()

        import pandas as pd
        import sqlite3

        conn = sqlite3.connect(self.db.db_path)
        high_risk_df = pd.read_sql_query(
            "SELECT * FROM fraud_results WHERE risk_score >= 50 ORDER BY risk_score DESC LIMIT 10",
            conn
        )
        conn.close()

        if high_risk_df.empty:
            console.print("[yellow]No high-risk accounts found[/yellow]")
        else:
            console.print(f"[bold red]🔔 {len(high_risk_df)} HIGH RISK ACCOUNTS[/bold red]\n")

            alerts_table = Table(box=box.ROUNDED)
            alerts_table.add_column("#", style="blue", width=3)
            alerts_table.add_column("Email", style="black", width=30)
            alerts_table.add_column("DUID", style="black", width=12)
            alerts_table.add_column("Risk", style="red", justify="right", width=6)
            alerts_table.add_column("Payout", style="dark_orange", justify="right", width=10)

            for idx, row in high_risk_df.iterrows():
                alerts_table.add_row(
                    str(idx + 1),
                    row['email'][:28] + "..." if len(str(row['email'])) > 28 else str(row['email']),
                    str(row['duid']),
                    str(row['risk_score']),
                    f"${row['payout_amount']:.2f}"
                )

            console.print(alerts_table)

        Prompt.ask("\nPress Enter to continue")

    def export_reports(self):
        """Export reports"""
        self.show_header()
        console.print(Panel("📁 EXPORT REPORTS", style="bold blue"))
        console.print()

        console.print("[yellow]Export feature: Use the reports/ directory[/yellow]")
        console.print("Reports are automatically saved after each analysis.")

        Prompt.ask("\nPress Enter to continue")

    def test_single_email(self):
        """Test single email analysis"""
        self.show_header()
        console.print(Panel("🧪 TEST MODE - Analyze Single Email", style="bold blue"))
        console.print()

        email = Prompt.ask("Enter email address to analyze")

        # Import fraud detection script
        sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
        from email_fraud_detector import EmailFraudDetector

        console.print("\n🔄 Analyzing email...\n")

        detector = EmailFraudDetector()
        analysis = detector.analyze_email(email)

        console.print(Panel("ANALYSIS RESULTS", style="bold green"))
        console.print()

        result_table = Table(show_header=False, box=box.SIMPLE)
        result_table.add_column("Field", style="blue")
        result_table.add_column("Value", style="black")

        result_table.add_row("Email", analysis['email'])
        result_table.add_row("Risk Score", f"[red]{analysis['risk_score']}[/red] / 100")

        risk_level = "🔴 HIGH RISK" if analysis['risk_score'] >= 50 else "🟡 MEDIUM RISK" if analysis['risk_score'] >= 25 else "🟢 LOW RISK"
        result_table.add_row("Risk Level", risk_level)

        if analysis['flags']:
            result_table.add_row("Flags", ", ".join(analysis['flags']))

        if analysis['details']:
            result_table.add_row("Details", str(analysis['details']))

        console.print(result_table)

        if Confirm.ask("\nTest another email?"):
            self.test_single_email()

    def view_logs(self):
        """View recent logs"""
        self.show_header()
        console.print(Panel("📖 RECENT LOGS", style="bold blue"))
        console.print()

        log_file = 'fraud_detection.log'
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                lines = f.readlines()
                recent_lines = lines[-50:]  # Last 50 lines

            for line in recent_lines:
                console.print(line.strip())
        else:
            console.print("[yellow]No log file found[/yellow]")

        Prompt.ask("\nPress Enter to continue")

    def temporal_analysis(self):
        """Temporal analysis of fraud patterns"""
        self.show_header()
        console.print(Panel("🔬 TEMPORAL ANALYSIS", style="bold blue"))
        console.print()
        
        # Get fraud results
        console.print("[yellow]Loading fraud results...[/yellow]")
        df = self.db.get_fraud_results()
        
        if df.empty:
            console.print("[red]❌ No fraud results found![/red]")
            console.print("Please run fraud detection first (Option 2).")
            Prompt.ask("\nPress Enter to continue")
            return
        
        # Check if we have date information
        if 'analyzed_at' not in df.columns:
            console.print("[yellow]⚠️  No date information available in results[/yellow]")
            console.print("Temporal analysis requires date information.")
            Prompt.ask("\nPress Enter to continue")
            return
        
        import pandas as pd
        df['analyzed_at'] = pd.to_datetime(df['analyzed_at'])
        df = df.sort_values('analyzed_at')
        
        console.print(f"[green]✓ Loaded {len(df):,} records[/green]\n")
        
        # Daily trends
        console.print("[bold green]Daily Fraud Trends:[/bold green]\n")
        
        daily_stats = df.groupby(df['analyzed_at'].dt.date).agg({
            'duid': 'count',
            'risk_score': 'mean',
            'payout_amount': 'sum'
        }).rename(columns={'duid': 'count', 'risk_score': 'avg_risk', 'payout_amount': 'total_payout'})
        
        trend_table = Table(box=box.ROUNDED)
        trend_table.add_column("Date", style="blue")
        trend_table.add_column("Accounts", justify="right", style="black")
        trend_table.add_column("Avg Risk", justify="right", style="black")
        trend_table.add_column("Total Payout", justify="right", style="black")
        
        for date, row in daily_stats.tail(14).iterrows():
            trend_table.add_row(
                str(date),
                f"{int(row['count']):,}",
                f"{row['avg_risk']:.1f}",
                f"${row['total_payout']:.2f}"
            )
        
        console.print(trend_table)
        
        # High risk over time
        high_risk_daily = df[df['risk_score'] >= 50].groupby(df['analyzed_at'].dt.date).size()
        
        if len(high_risk_daily) > 0:
            console.print("\n[bold green]High Risk Accounts (Last 14 Days):[/bold green]\n")
            hr_table = Table(box=box.ROUNDED)
            hr_table.add_column("Date", style="blue")
            hr_table.add_column("High Risk Count", justify="right", style="red")
            hr_table.add_column("% of Total", justify="right", style="black")
            
            for date in daily_stats.tail(14).index:
                hr_count = high_risk_daily.get(date, 0)
                total = daily_stats.loc[date, 'count']
                pct = (hr_count / total * 100) if total > 0 else 0
                hr_table.add_row(str(date), f"{int(hr_count):,}", f"{pct:.1f}%")
            
            console.print(hr_table)
        
        # Summary statistics
        console.print("\n[bold green]Summary Statistics:[/bold green]\n")
        summary_table = Table(box=box.ROUNDED, show_header=False)
        summary_table.add_column("Metric", style="blue")
        summary_table.add_column("Value", style="black")
        
        summary_table.add_row("Total Records", f"{len(df):,}")
        summary_table.add_row("Date Range", f"{df['analyzed_at'].min().date()} to {df['analyzed_at'].max().date()}")
        summary_table.add_row("Days Analyzed", f"{(df['analyzed_at'].max() - df['analyzed_at'].min()).days + 1}")
        summary_table.add_row("Avg Daily Accounts", f"{len(df) / max((df['analyzed_at'].max() - df['analyzed_at'].min()).days + 1, 1):.1f}")
        summary_table.add_row("Avg Daily High Risk", f"{len(df[df['risk_score'] >= 50]) / max((df['analyzed_at'].max() - df['analyzed_at'].min()).days + 1, 1):.1f}")
        
        console.print(summary_table)
        
        Prompt.ask("\nPress Enter to continue")

    def pattern_discovery(self):
        """Pattern discovery menu"""
        while True:
            self.show_header()
            console.print(Panel("🔎 PATTERN DISCOVERY", style="bold blue"))
            console.print()
            
            console.print("[bold black]Select analysis scope:[/bold black]")
            console.print("  1. All Data")
            console.print("  2. High Risk Only (risk ≥ 50)")
            console.print("  3. Medium+ Risk (risk ≥ 25)")
            console.print("  4. Latest Session")
            console.print("  5. Last 30 Days")
            console.print("  0. Back to Main Menu")
            
            scope_choice = Prompt.ask("Choice", choices=["0", "1", "2", "3", "4", "5"], default="1")
            
            if scope_choice == "0":
                return
            
            # Get data based on scope
            min_risk = None
            if scope_choice == "2":
                min_risk = 50
            elif scope_choice == "3":
                min_risk = 25
            
            console.print("\n[yellow]Loading data...[/yellow]")
            df = self.db.get_fraud_results(min_risk=min_risk)
            
            if df.empty:
                console.print("[red]❌ No data found for selected scope![/red]")
                Prompt.ask("\nPress Enter to continue")
                continue
            
            console.print(f"[green]✓ Loaded {len(df):,} records[/green]\n")
            
            # Pattern analysis
            console.print("[bold green]Pattern Analysis:[/bold green]\n")
            
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
                flag_table = Table(box=box.ROUNDED)
                flag_table.add_column("Flag", style="blue")
                flag_table.add_column("Count", justify="right", style="black")
                flag_table.add_column("% of Records", justify="right", style="black")
                
                for flag, count in sorted(flag_counts.items(), key=lambda x: x[1], reverse=True):
                    pct = (count / len(df) * 100) if len(df) > 0 else 0
                    flag_table.add_row(flag, f"{count:,}", f"{pct:.1f}%")
                
                console.print(flag_table)
            
            # Domain analysis
            if 'email' in df.columns:
                console.print("\n[bold green]Top Email Domains:[/bold green]\n")
                domains = df['email'].str.extract(r'@([^.]+\.\w+)')[0].value_counts().head(10)
                domain_table = Table(box=box.ROUNDED)
                domain_table.add_column("Domain", style="blue")
                domain_table.add_column("Count", justify="right", style="black")
                domain_table.add_column("% of Records", justify="right", style="black")
                
                for domain, count in domains.items():
                    pct = (count / len(df) * 100) if len(df) > 0 else 0
                    domain_table.add_row(domain, f"{count:,}", f"{pct:.1f}%")
                
                console.print(domain_table)
            
            # Risk score distribution
            console.print("\n[bold green]Risk Score Distribution:[/bold green]\n")
            risk_table = Table(box=box.ROUNDED)
            risk_table.add_column("Range", style="blue")
            risk_table.add_column("Count", justify="right", style="black")
            risk_table.add_column("Avg Payout", justify="right", style="black")
            
            ranges = [
                (0, 24, "Low (0-24)"),
                (25, 49, "Medium (25-49)"),
                (50, 74, "High (50-74)"),
                (75, 100, "Very High (75-100)")
            ]
            
            for min_r, max_r, label in ranges:
                subset = df[(df['risk_score'] >= min_r) & (df['risk_score'] <= max_r)]
                count = len(subset)
                avg_payout = subset['payout_amount'].mean() if count > 0 else 0
                risk_table.add_row(label, f"{count:,}", f"${avg_payout:.2f}")
            
            console.print(risk_table)
            
            # Export option
            if Confirm.ask("\n[bold]Export pattern analysis to CSV?[/bold]"):
                from pathlib import Path
                reports_dir = Path("reports")
                reports_dir.mkdir(exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = reports_dir / f"pattern_analysis_{timestamp}.csv"
                df.to_csv(filename, index=False)
                console.print(f"[green]✓ Exported to {filename}[/green]")
            
            if not Confirm.ask("\n[bold]Run another analysis?[/bold]"):
                break

    def cluster_analysis(self):
        """Cluster analysis of fraud patterns"""
        self.show_header()
        console.print(Panel("📊 CLUSTER ANALYSIS", style="bold blue"))
        console.print()
        
        # Get fraud results
        console.print("[yellow]Loading fraud results...[/yellow]")
        df = self.db.get_fraud_results()
        
        if df.empty:
            console.print("[red]❌ No fraud results found![/red]")
            console.print("Please run fraud detection first (Option 2).")
            Prompt.ask("\nPress Enter to continue")
            return
        
        console.print(f"[green]✓ Loaded {len(df):,} records[/green]\n")
        
        # IP clustering
        if 'ip' in df.columns:
            console.print("[bold green]IP Address Clusters:[/bold green]\n")
            ip_counts = df['ip'].value_counts()
            ip_clusters = ip_counts[ip_counts > 1].head(10)
            
            if len(ip_clusters) > 0:
                ip_table = Table(box=box.ROUNDED)
                ip_table.add_column("IP Address", style="blue")
                ip_table.add_column("Account Count", justify="right", style="black")
                ip_table.add_column("Avg Risk Score", justify="right", style="black")
                ip_table.add_column("Total Payout", justify="right", style="black")
                
                for ip, count in ip_clusters.items():
                    ip_df = df[df['ip'] == ip]
                    avg_risk = ip_df['risk_score'].mean()
                    total_payout = ip_df['payout_amount'].sum()
                    ip_table.add_row(
                        ip,
                        f"{count:,}",
                        f"{avg_risk:.1f}",
                        f"${total_payout:.2f}"
                    )
                
                console.print(ip_table)
            else:
                console.print("[dim]No IP address clusters found (all unique IPs)[/dim]")
        
        # Domain clustering
        if 'email' in df.columns:
            console.print("\n[bold green]Email Domain Clusters:[/bold green]\n")
            domains = df['email'].str.extract(r'@([^.]+\.\w+)')[0]
            domain_counts = domains.value_counts()
            domain_clusters = domain_counts[domain_counts > 1].head(10)
            
            if len(domain_clusters) > 0:
                domain_table = Table(box=box.ROUNDED)
                domain_table.add_column("Domain", style="blue")
                domain_table.add_column("Account Count", justify="right", style="black")
                domain_table.add_column("Avg Risk Score", justify="right", style="black")
                domain_table.add_column("Total Payout", justify="right", style="black")
                
                for domain, count in domain_clusters.items():
                    domain_df = df[df['email'].str.contains(f'@{domain}', na=False)]
                    avg_risk = domain_df['risk_score'].mean()
                    total_payout = domain_df['payout_amount'].sum()
                    domain_table.add_row(
                        domain,
                        f"{count:,}",
                        f"{avg_risk:.1f}",
                        f"${total_payout:.2f}"
                    )
                
                console.print(domain_table)
        
        # Geographic clustering
        if 'geo_country' in df.columns:
            console.print("\n[bold green]Geographic Clusters:[/bold green]\n")
            country_counts = df['geo_country'].value_counts().head(10)
            
            if len(country_counts) > 0:
                geo_table = Table(box=box.ROUNDED)
                geo_table.add_column("Country", style="blue")
                geo_table.add_column("Account Count", justify="right", style="black")
                geo_table.add_column("Avg Risk Score", justify="right", style="black")
                geo_table.add_column("Total Payout", justify="right", style="black")
                
                for country, count in country_counts.items():
                    country_df = df[df['geo_country'] == country]
                    avg_risk = country_df['risk_score'].mean()
                    total_payout = country_df['payout_amount'].sum()
                    geo_table.add_row(
                        country or "Unknown",
                        f"{count:,}",
                        f"{avg_risk:.1f}",
                        f"${total_payout:.2f}"
                    )
                
                console.print(geo_table)
        
        # Flag pattern clusters
        import json
        flag_combinations = {}
        for flags_str in df['flags'].fillna('[]'):
            try:
                flags = json.loads(flags_str) if isinstance(flags_str, str) else flags_str
                flag_key = ','.join(sorted(flags)) if flags else 'none'
                flag_combinations[flag_key] = flag_combinations.get(flag_key, 0) + 1
            except:
                continue
        
        if flag_combinations:
            console.print("\n[bold green]Flag Pattern Clusters:[/bold green]\n")
            flag_table = Table(box=box.ROUNDED)
            flag_table.add_column("Flag Combination", style="blue")
            flag_table.add_column("Count", justify="right", style="black")
            flag_table.add_column("% of Records", justify="right", style="black")
            
            for combo, count in sorted(flag_combinations.items(), key=lambda x: x[1], reverse=True)[:10]:
                pct = (count / len(df) * 100) if len(df) > 0 else 0
                display_combo = combo[:50] + "..." if len(combo) > 50 else combo
                flag_table.add_row(display_combo, f"{count:,}", f"{pct:.1f}%")
            
            console.print(flag_table)
        
        Prompt.ask("\nPress Enter to continue")

    def ensemble_anomaly_detection(self):
        """Ensemble anomaly detection"""
        self.show_header()
        console.print(Panel("🎯 ENSEMBLE ANOMALY DETECTION", style="bold blue"))
        console.print()
        
        try:
            from pattern_detector import AnomalyDetector, PYOD_AVAILABLE
        except ImportError:
            console.print("[red]❌ Pattern detector module not found![/red]")
            console.print("Please ensure pattern_detector.py exists in the project directory.")
            Prompt.ask("\nPress Enter to continue")
            return

        if not PYOD_AVAILABLE:
            console.print("[red]❌ PyOD library not installed![/red]")
            console.print("Install with: pip install pyod")
            console.print("\n[yellow]Note: This feature requires PyOD for ML-based anomaly detection.[/yellow]")
            console.print("You can still use rule-based detection (Option 2).")
            Prompt.ask("\nPress Enter to continue")
            return
        
        # Get data type
        console.print("[bold black]Select data type to analyze:[/bold black]")
        console.print("  1. Free (Leads)")
        console.print("  2. Paid (Sales)")
        console.print("  3. Both")
        data_type_choice = Prompt.ask("Choice", choices=["1", "2", "3"], default="3")
        
        data_type = None
        if data_type_choice == "1":
            data_type = "free"
        elif data_type_choice == "2":
            data_type = "paid"
        
        # Get fraud results
        console.print("\n[yellow]Loading fraud results...[/yellow]")
        df = self.db.get_fraud_results(data_type=data_type)
        
        if df.empty or len(df) < 10:
            console.print("[red]❌ Insufficient data for ensemble detection![/red]")
            console.print(f"Found {len(df)} records. Need at least 10 records.")
            console.print("Please run fraud detection first (Option 2).")
            Prompt.ask("\nPress Enter to continue")
            return
        
        console.print(f"[green]✓ Loaded {len(df):,} records[/green]")
        console.print("\n[yellow]Running ensemble anomaly detection...[/yellow]")
        console.print("   (Combining rule-based + ML-based detection)\n")
        
        # Run ML anomaly detection
        try:
            detector = AnomalyDetector(contamination=0.1)
            ml_results = detector.fit_predict(df)
        except Exception as e:
            console.print(f"[red]❌ Error running ML detection: {e}[/red]")
            logger.exception("Ensemble detection error")
            Prompt.ask("\nPress Enter to continue")
            return
        
        if not ml_results or 'consensus' not in ml_results:
            console.print("[red]❌ ML detection failed![/red]")
            Prompt.ask("\nPress Enter to continue")
            return
        
        # Combine rule-based and ML-based
        import pandas as pd
        console.print("[bold green]Ensemble Detection Results:[/bold green]\n")
        
        # Rule-based high risk
        rule_high_risk = df[df['risk_score'] >= 50]
        
        # ML consensus anomalies
        ml_anomalies = ml_results['consensus']['predictions']
        ml_flagged = df[ml_anomalies.astype(bool)]
        
        # Combined (either rule-based OR ML-based)
        combined = pd.concat([rule_high_risk, ml_flagged]).drop_duplicates(subset=['duid'])
        
        # Both (rule-based AND ML-based)
        both_flagged = rule_high_risk[rule_high_risk['duid'].isin(ml_flagged['duid'])]
        
        # ML-only (missed by rules)
        ml_only = ml_flagged[~ml_flagged['duid'].isin(rule_high_risk['duid'])]
        
        # Rule-only (missed by ML)
        rule_only = rule_high_risk[~rule_high_risk['duid'].isin(ml_flagged['duid'])]
        
        ensemble_table = Table(box=box.ROUNDED)
        ensemble_table.add_column("Detection Method", style="blue")
        ensemble_table.add_column("Accounts Flagged", justify="right", style="black")
        ensemble_table.add_column("Total Payout", justify="right", style="black")
        ensemble_table.add_column("Avg Risk/Score", justify="right", style="black")
        
        ensemble_table.add_row(
            "Rule-Based Only",
            f"{len(rule_only):,}",
            f"${rule_only['payout_amount'].sum():.2f}",
            f"{rule_only['risk_score'].mean():.1f}"
        )
        
        # Calculate average ML score for ML-only accounts
        ml_only_scores = []
        if len(ml_only) > 0:
            ml_scores = ml_results['consensus']['scores']
            ml_only_indices = [i for i, duid in enumerate(df['duid']) if duid in ml_only['duid'].values]
            ml_only_scores = [ml_scores[i] for i in ml_only_indices if i < len(ml_scores)]
        
        avg_ml_score = sum(ml_only_scores) / len(ml_only_scores) if ml_only_scores else 0
        
        ensemble_table.add_row(
            "ML-Based Only",
            f"{len(ml_only):,}",
            f"${ml_only['payout_amount'].sum():.2f}",
            f"{avg_ml_score:.2f}"
        )
        
        ensemble_table.add_row(
            "[bold green]Both (High Confidence)[/bold green]",
            f"[bold green]{len(both_flagged):,}[/bold green]",
            f"[bold green]${both_flagged['payout_amount'].sum():.2f}[/bold green]",
            f"[bold green]{both_flagged['risk_score'].mean():.1f}[/bold green]"
        )
        
        ensemble_table.add_row(
            "[bold yellow]Combined (Either Method)[/bold yellow]",
            f"[bold yellow]{len(combined):,}[/bold yellow]",
            f"[bold yellow]${combined['payout_amount'].sum():.2f}[/bold yellow]",
            f"[bold yellow]{combined['risk_score'].mean():.1f}[/bold yellow]"
        )
        
        console.print(ensemble_table)
        
        # Show newly discovered by ML
        if len(ml_only) > 0:
            console.print(f"\n[bold yellow]⚠️  {len(ml_only)} accounts flagged by ML but missed by rules:[/bold yellow]\n")
            
            ml_table = Table(box=box.ROUNDED)
            ml_table.add_column("Email", style="black")
            ml_table.add_column("Rule Risk", justify="right", style="black")
            ml_table.add_column("ML Score", justify="right", style="black")
            ml_table.add_column("Payout", justify="right", style="black")
            
            ml_scores = ml_results['consensus']['scores']
            for idx, row in ml_only.head(10).iterrows():
                # Find the index in original df
                duid = row.get('duid')
                df_idx = df[df['duid'] == duid].index
                if len(df_idx) > 0 and df_idx[0] < len(ml_scores):
                    score = ml_scores[df_idx[0]]
                else:
                    score = 0
                
                ml_table.add_row(
                    row.get('email', 'Unknown')[:40],
                    str(int(row.get('risk_score', 0))),
                    f"{score:.2f}",
                    f"${row.get('payout_amount', 0):.2f}"
                )
            
            console.print(ml_table)
            
            if len(ml_only) > 10:
                console.print(f"\n[dim]... and {len(ml_only) - 10} more accounts[/dim]")
        
        # Export option
        if Confirm.ask("\n[bold]Export ensemble results to CSV?[/bold]"):
            from pathlib import Path
            reports_dir = Path("reports")
            reports_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = reports_dir / f"ensemble_detection_{timestamp}.csv"
            combined.to_csv(filename, index=False)
            console.print(f"[green]✓ Exported to {filename}[/green]")
        
        Prompt.ask("\nPress Enter to continue")

    def advanced_anomaly_detection(self):
        """Advanced anomaly detection using ML"""
        self.show_header()
        console.print(Panel("🤖 ADVANCED ANOMALY DETECTION", style="bold blue"))
        console.print()
        
        try:
            from pattern_detector import AnomalyDetector, PYOD_AVAILABLE
        except ImportError:
            console.print("[red]❌ Pattern detector module not found![/red]")
            console.print("Please ensure pattern_detector.py exists in the project directory.")
            Prompt.ask("\nPress Enter to continue")
            return

        if not PYOD_AVAILABLE:
            console.print("[red]❌ PyOD library not installed![/red]")
            console.print("Install with: pip install pyod")
            Prompt.ask("\nPress Enter to continue")
            return

        # Get data type
        console.print("[bold black]Select data type to analyze:[/bold black]")
        console.print("  1. Free (Leads)")
        console.print("  2. Paid (Sales)")
        console.print("  3. Both")
        data_type_choice = Prompt.ask("Choice", choices=["1", "2", "3"], default="3")
        
        data_type = None
        if data_type_choice == "1":
            data_type = "free"
        elif data_type_choice == "2":
            data_type = "paid"
        
        # Get fraud results
        console.print("\n[yellow]Loading fraud results...[/yellow]")
        df = self.db.get_fraud_results(data_type=data_type)
        
        if df.empty or len(df) < 10:
            console.print("[red]❌ Insufficient data for anomaly detection![/red]")
            console.print(f"Found {len(df)} records. Need at least 10 records.")
            console.print("Please run fraud detection first (Option 2).")
            Prompt.ask("\nPress Enter to continue")
            return
        
        console.print(f"[green]✓ Loaded {len(df):,} records[/green]")
        console.print("\n[yellow]Running anomaly detection algorithms...[/yellow]")
        
        # Initialize detector
        try:
            detector = AnomalyDetector(contamination=0.1)
            results = detector.fit_predict(df)
        except Exception as e:
            console.print(f"[red]❌ Error running anomaly detection: {e}[/red]")
            logger.exception("Anomaly detection error")
            Prompt.ask("\nPress Enter to continue")
            return
        
        if not results:
            console.print("[red]❌ Anomaly detection failed![/red]")
            Prompt.ask("\nPress Enter to continue")
            return
        
        # Display results
        console.print("\n[bold green]Anomaly Detection Results:[/bold green]\n")
        
        results_table = Table(box=box.ROUNDED)
        results_table.add_column("Algorithm", style="blue")
        results_table.add_column("Anomalies Detected", justify="right", style="black")
        results_table.add_column("% of Total", justify="right", style="black")
        
        total_records = len(df)
        for name, result in results.items():
            if name == 'consensus':
                continue
            anomaly_count = result.get('anomaly_count', 0)
            percentage = (anomaly_count / total_records * 100) if total_records > 0 else 0
            results_table.add_row(
                name,
                f"{anomaly_count:,}",
                f"{percentage:.1f}%"
            )
        
        # Add consensus
        if 'consensus' in results:
            consensus_count = results['consensus'].get('anomaly_count', 0)
            consensus_pct = (consensus_count / total_records * 100) if total_records > 0 else 0
            results_table.add_row(
                "[bold red]CONSENSUS (2+ agree)[/bold red]",
                f"[bold red]{consensus_count:,}[/bold red]",
                f"[bold red]{consensus_pct:.1f}%[/bold red]"
            )
        
        console.print(results_table)
        
        # Find missed fraud
        if 'consensus' in results:
            missed_fraud = detector.find_missed_fraud(df, results, risk_threshold=50)
            
            if len(missed_fraud) > 0:
                console.print(f"\n[bold yellow]⚠️  FOUND {len(missed_fraud)} POTENTIAL FRAUDS MISSED BY RULES![/bold yellow]\n")
                
                missed_table = Table(box=box.ROUNDED)
                missed_table.add_column("Email", style="black")
                missed_table.add_column("Rule Risk", justify="right", style="black")
                missed_table.add_column("Anomaly Score", justify="right", style="black")
                missed_table.add_column("Payout", justify="right", style="black")
                
                for idx, row in missed_fraud.head(20).iterrows():
                    email = row.get('email', 'Unknown')
                    risk = int(row.get('risk_score', 0))
                    payout = row.get('payout_amount', 0)
                    
                    # Get average anomaly score
                    scores = []
                    for name in ['IsolationForest', 'KNN', 'LOF']:
                        if f'{name}_score' in row:
                            scores.append(row[f'{name}_score'])
                    avg_score = sum(scores) / len(scores) if scores else 0
                    
                    missed_table.add_row(
                        email[:40],
                        str(risk),
                        f"{avg_score:.2f}",
                        f"${payout:.2f}"
                    )
                
                console.print(missed_table)
                
                if len(missed_fraud) > 20:
                    console.print(f"\n[dim]... and {len(missed_fraud) - 20} more accounts[/dim]")
                
                # Export option
                if Confirm.ask("\n[bold]Export newly discovered frauds to CSV?[/bold]"):
                    from pathlib import Path
                    import pandas as pd
                    
                    reports_dir = Path("reports")
                    reports_dir.mkdir(exist_ok=True)
                    
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = reports_dir / f"anomaly_detected_fraud_{timestamp}.csv"
                    
                    missed_fraud.to_csv(filename, index=False)
                    console.print(f"[green]✓ Exported to {filename}[/green]")
        
        Prompt.ask("\nPress Enter to continue")

    def drift_monitoring(self):
        """Drift monitoring for fraud pattern changes"""
        self.show_header()
        console.print(Panel("📉 DRIFT MONITORING", style="bold blue"))
        console.print()
        
        try:
            from pattern_detector import DriftDetector, ALIBI_AVAILABLE
        except ImportError:
            console.print("[red]❌ Pattern detector module not found![/red]")
            console.print("Please ensure pattern_detector.py exists in the project directory.")
            Prompt.ask("\nPress Enter to continue")
            return

        if not ALIBI_AVAILABLE:
            console.print("[red]❌ Alibi Detect library not installed![/red]")
            console.print("Install with: pip install alibi-detect")
            Prompt.ask("\nPress Enter to continue")
            return

        # Select reference period
        console.print("[bold black]Select reference period (historical baseline):[/bold black]")
        console.print("  1. Last 30 days")
        console.print("  2. Last 60 days")
        console.print("  3. Last 90 days")
        ref_choice = Prompt.ask("Choice", choices=["1", "2", "3"], default="2")
        
        ref_days = {1: 30, 2: 60, 3: 90}[int(ref_choice)]
        
        # Select current period
        console.print("\n[bold black]Select current period (recent data):[/bold black]")
        console.print("  1. Last 7 days")
        console.print("  2. Last 14 days")
        console.print("  3. Last 30 days")
        curr_choice = Prompt.ask("Choice", choices=["1", "2", "3"], default="1")
        
        curr_days = {1: 7, 2: 14, 3: 30}[int(curr_choice)]
        
        console.print(f"\n[yellow]Loading reference data (last {ref_days} days)...[/yellow]")
        
        # Get reference data
        import pandas as pd
        from datetime import datetime, timedelta
        
        ref_end = datetime.now() - timedelta(days=curr_days)
        ref_start = ref_end - timedelta(days=ref_days)
        
        # Get fraud results with date filtering
        all_df = self.db.get_fraud_results()
        
        if all_df.empty:
            console.print("[red]❌ No fraud results found![/red]")
            console.print("Please run fraud detection first (Option 2).")
            Prompt.ask("\nPress Enter to continue")
            return
        
        # Filter by date if analyzed_at exists
        if 'analyzed_at' in all_df.columns:
            all_df['analyzed_at'] = pd.to_datetime(all_df['analyzed_at'])
            ref_df = all_df[(all_df['analyzed_at'] >= ref_start) & (all_df['analyzed_at'] < ref_end)]
            curr_df = all_df[all_df['analyzed_at'] >= ref_end]
        else:
            # Fallback: use all data for reference, recent for current
            ref_df = all_df.head(int(len(all_df) * 0.7))  # First 70% as reference
            curr_df = all_df.tail(int(len(all_df) * 0.3))  # Last 30% as current
        
        if len(ref_df) < 100:
            console.print(f"[red]❌ Insufficient reference data![/red]")
            console.print(f"Found {len(ref_df)} records. Need at least 100 records.")
            Prompt.ask("\nPress Enter to continue")
            return
        
        if len(curr_df) < 20:
            console.print(f"[red]❌ Insufficient current data![/red]")
            console.print(f"Found {len(curr_df)} records. Need at least 20 records.")
            Prompt.ask("\nPress Enter to continue")
            return
        
        console.print(f"[green]✓ Reference: {len(ref_df):,} records[/green]")
        console.print(f"[green]✓ Current: {len(curr_df):,} records[/green]")
        console.print("\n[yellow]Running drift detection...[/yellow]")
        
        try:
            detector = DriftDetector(reference_window_days=ref_days)
            detector.set_reference_data(ref_df)
            drift_result = detector.check_drift(curr_df)
        except Exception as e:
            console.print(f"[red]❌ Error running drift detection: {e}[/red]")
            logger.exception("Drift detection error")
            Prompt.ask("\nPress Enter to continue")
            return
        
        # Display results
        console.print("\n[bold green]Drift Detection Results:[/bold green]\n")
        
        results_table = Table(box=box.ROUNDED, show_header=False)
        results_table.add_column("Metric", style="blue")
        results_table.add_column("Value", style="black")
        
        is_drift = drift_result.get('is_drift', False)
        p_value = drift_result.get('p_value', 0)
        
        if is_drift:
            results_table.add_row("Drift Detected", "[bold red]YES ⚠️[/bold red]")
            results_table.add_row("Status", "[bold red]Fraud patterns have changed![/bold red]")
        else:
            results_table.add_row("Drift Detected", "[bold green]NO ✓[/bold green]")
            results_table.add_row("Status", "[bold green]Fraud patterns remain stable[/bold green]")
        
        results_table.add_row("P-Value", f"{p_value:.4f}")
        results_table.add_row("Reference Records", f"{drift_result.get('reference_size', 0):,}")
        results_table.add_row("Current Records", f"{drift_result.get('current_size', 0):,}")
        
        console.print(results_table)
        
        # Interpretation
        console.print("\n[bold black]Interpretation:[/bold black]")
        if p_value < 0.05:
            console.print("[red]⚠️  Significant drift detected (p < 0.05)[/red]")
            console.print("   → Consider updating your detection rules")
            console.print("   → Review recent fraud patterns")
        elif p_value < 0.10:
            console.print("[yellow]⚠️  Marginal drift detected (0.05 ≤ p < 0.10)[/yellow]")
            console.print("   → Monitor closely")
        else:
            console.print("[green]✓ No significant drift (p ≥ 0.10)[/green]")
            console.print("   → Current detection rules are still effective")
        
        Prompt.ask("\nPress Enter to continue")


def main():
    """Main entry point"""
    try:
        cli = FraudDetectionCLI()
        cli.main_menu()
    except KeyboardInterrupt:
        console.print("\n\n[bold yellow]Operation cancelled by user[/bold yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[bold red]Fatal error: {e}[/bold red]")
        logger.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
