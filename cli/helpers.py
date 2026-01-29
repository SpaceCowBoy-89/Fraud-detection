"""
CLI Helper utilities for consistent UI/UX

Provides:
- Responsive table creation
- Common prompts
- Status displays
- Color theming
"""

import sys
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme
from rich import box

# Custom theme optimized for both light and dark backgrounds
custom_theme = Theme({
    "info": "black",
    "warning": "dark_orange",
    "error": "red",
    "success": "dark_green",
    "highlight": "bold blue",
    "menu": "black",
    "value": "black bold",
    "header": "bold blue",
    "subheader": "bold black",
    "dim": "dim",
    "risk_high": "bold red",
    "risk_medium": "bold yellow",
    "risk_low": "bold green",
})

# Global console instance
console = Console(theme=custom_theme)


class CLIHelpers:
    """Helper class for common CLI operations"""
    
    # Terminal width breakpoints
    NARROW = 80
    MEDIUM = 120
    WIDE = 160
    
    @staticmethod
    def get_terminal_width():
        """Get current terminal width"""
        return console.width
    
    @staticmethod
    def is_narrow():
        """Check if terminal is narrow (<80 chars)"""
        return console.width < CLIHelpers.NARROW
    
    @staticmethod
    def is_medium():
        """Check if terminal is medium (80-120 chars)"""
        return CLIHelpers.NARROW <= console.width < CLIHelpers.MEDIUM
    
    @staticmethod
    def is_wide():
        """Check if terminal is wide (>120 chars)"""
        return console.width >= CLIHelpers.MEDIUM
    
    @staticmethod
    def create_table(columns, title=None, box_style=box.ROUNDED, show_header=True):
        """
        Create a responsive table that adapts to terminal width.
        
        Args:
            columns: List of dicts with 'name', 'style', 'width', 'justify', 'priority'
                     Priority: 1=always show, 2=medium+, 3=wide only
            title: Optional table title
            box_style: Rich box style
            show_header: Whether to show column headers
        
        Returns:
            Table object with appropriate columns for terminal width
        """
        table = Table(title=title, box=box_style, show_header=show_header)
        
        width = CLIHelpers.get_terminal_width()
        
        for col in columns:
            priority = col.get('priority', 1)
            
            # Filter columns based on terminal width
            if priority == 3 and width < CLIHelpers.MEDIUM:
                continue
            if priority == 2 and width < CLIHelpers.NARROW:
                continue
            
            # Adjust widths for narrow terminals
            col_width = col.get('width')
            if col_width and width < CLIHelpers.NARROW:
                col_width = max(col_width - 5, 8)
            
            table.add_column(
                col['name'],
                style=col.get('style', 'black'),
                width=col_width,
                justify=col.get('justify', 'left'),
                no_wrap=col.get('no_wrap', False)
            )
        
        return table
    
    @staticmethod
    def truncate(text, max_length, suffix="..."):
        """Truncate text to max length with suffix"""
        if not text:
            return ""
        text = str(text)
        if len(text) <= max_length:
            return text
        return text[:max_length - len(suffix)] + suffix
    
    @staticmethod
    def format_currency(amount, include_symbol=True):
        """Format currency amount"""
        if amount is None:
            return "N/A"
        try:
            amount = float(amount)
            if include_symbol:
                return f"${amount:,.2f}"
            return f"{amount:,.2f}"
        except (ValueError, TypeError):
            return "N/A"
    
    @staticmethod
    def format_percentage(value, decimals=1):
        """Format percentage value"""
        if value is None:
            return "N/A"
        try:
            return f"{float(value) * 100:.{decimals}f}%"
        except (ValueError, TypeError):
            return "N/A"
    
    @staticmethod
    def format_risk_score(score):
        """Format risk score with color"""
        try:
            score = int(score)
            if score >= 50:
                return f"[risk_high]{score}[/risk_high]"
            elif score >= 25:
                return f"[risk_medium]{score}[/risk_medium]"
            else:
                return f"[risk_low]{score}[/risk_low]"
        except (ValueError, TypeError):
            return "N/A"
    
    @staticmethod
    def risk_indicator(score):
        """Get risk level indicator emoji"""
        try:
            score = int(score)
            if score >= 50:
                return "🔴"
            elif score >= 25:
                return "🟡"
            else:
                return "🟢"
        except (ValueError, TypeError):
            return "⚪"
    
    @staticmethod
    def show_header(title="FRAUD DETECTION SYSTEM", version="v3.0"):
        """Display application header"""
        console.clear()
        header = Panel(
            Text(f"{title} {version}", style="bold black", justify="center"),
            style="blue",
            box=box.DOUBLE
        )
        console.print(header)
        console.print()
    
    @staticmethod
    def show_section(title, style="bold blue"):
        """Display a section header"""
        console.print(Panel(title, style=style))
        console.print()
    
    @staticmethod
    def show_error(message):
        """Display an error message"""
        console.print(f"[bold red]❌ {message}[/bold red]")
    
    @staticmethod
    def show_success(message):
        """Display a success message"""
        console.print(f"[bold green]✓ {message}[/bold green]")
    
    @staticmethod
    def show_warning(message):
        """Display a warning message"""
        console.print(f"[bold yellow]⚠️  {message}[/bold yellow]")
    
    @staticmethod
    def show_info(message):
        """Display an info message"""
        console.print(f"[dim]{message}[/dim]")
    
    @staticmethod
    def confirm(message, default=False):
        """Show confirmation prompt"""
        from rich.prompt import Confirm
        return Confirm.ask(message, default=default)
    
    @staticmethod
    def prompt(message, choices=None, default=None):
        """Show prompt with optional choices"""
        from rich.prompt import Prompt
        if choices:
            return Prompt.ask(message, choices=choices, default=default)
        return Prompt.ask(message, default=default)
    
    @staticmethod
    def prompt_int(message, default=None):
        """Show integer prompt"""
        from rich.prompt import IntPrompt
        return IntPrompt.ask(message, default=default)
    
    @staticmethod
    def wait_for_input(message="Press Enter to continue"):
        """Wait for user to press Enter"""
        from rich.prompt import Prompt
        Prompt.ask(f"\n{message}")
    
    @staticmethod
    def create_breadcrumb(path):
        """Create a navigation breadcrumb"""
        return " > ".join(path)
    
    @staticmethod
    def show_breadcrumb(path):
        """Display navigation breadcrumb"""
        breadcrumb = CLIHelpers.create_breadcrumb(path)
        console.print(f"[dim]{breadcrumb}[/dim]\n")
