"""
PDF Report Generator for EDA Results
Generates professional PDF reports from EDA analysis data.
"""

from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image as RLImage, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from datetime import datetime
from pathlib import Path
import json
import io

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Warning: matplotlib not installed. Charts will be skipped in PDF.")
    print("Install with: pip install matplotlib")


class EDAReportGenerator:
    """Generate PDF reports from EDA analysis results"""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Setup custom paragraph styles"""
        # Title style
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1e40af'),
            spaceAfter=30,
            alignment=TA_CENTER
        ))
        
        # Section header style
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#1e40af'),
            spaceBefore=20,
            spaceAfter=12,
            borderWidth=1,
            borderColor=colors.HexColor('#3b82f6'),
            borderPadding=5,
            backColor=colors.HexColor('#eff6ff')
        ))
        
        # Metric style
        self.styles.add(ParagraphStyle(
            name='Metric',
            parent=self.styles['Normal'],
            fontSize=11,
            leading=16,
            textColor=colors.HexColor('#374151')
        ))
        
        # Footer style
        self.styles.add(ParagraphStyle(
            name='Footer',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.gray,
            alignment=TA_CENTER
        ))
    
    def generate_pdf(self, eda_results, output_path, dataset_type='combined'):
        """
        Generate PDF report from EDA results
        
        Args:
            eda_results: Dict with EDA analysis results
            output_path: Path to save PDF file
            dataset_type: 'free', 'paid', or 'combined'
        
        Returns:
            Path to generated PDF file
        """
        # Create document
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=letter,
            rightMargin=0.75*inch,
            leftMargin=0.75*inch,
            topMargin=0.75*inch,
            bottomMargin=0.75*inch
        )
        
        # Build content
        story = []
        
        # Title page
        story.extend(self._build_title_page(eda_results, dataset_type))
        
        # Overview statistics
        if 'overview' in eda_results:
            story.extend(self._build_overview_section(eda_results['overview']))
        
        # Distribution analysis
        if 'distributions' in eda_results:
            story.extend(self._build_distributions_section(eda_results['distributions']))
        
        # Fraud correlations
        if 'fraud_correlations' in eda_results:
            story.extend(self._build_correlations_section(eda_results['fraud_correlations']))
        
        # Data quality issues
        if 'data_quality' in eda_results:
            story.extend(self._build_quality_section(eda_results['data_quality']))
        
        # Outliers
        if 'outliers' in eda_results:
            story.extend(self._build_outliers_section(eda_results['outliers']))
        
        # Build PDF
        doc.build(story)
        return output_path
    
    def _build_title_page(self, eda_results, dataset_type):
        """Build title page"""
        content = []
        
        # Title
        title = Paragraph("Exploratory Data Analysis Report", self.styles['CustomTitle'])
        content.append(title)
        content.append(Spacer(1, 0.3*inch))
        
        # Dataset info
        dataset_label = {
            'free': 'Free Accounts',
            'paid': 'Paid Accounts',
            'combined': 'All Accounts'
        }.get(dataset_type, 'Dataset')
        
        info_text = f"""
        <para alignment="center">
            <b>Dataset:</b> {dataset_label}<br/>
            <b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>
            <b>Report Type:</b> Fraud Detection - Data Quality & Patterns
        </para>
        """
        content.append(Paragraph(info_text, self.styles['Normal']))
        content.append(Spacer(1, 0.5*inch))
        
        # Key metrics summary (if available)
        if 'overview' in eda_results:
            overview = eda_results['overview']
            summary_data = [
                ['Metric', 'Value'],
                ['Total Records', f"{overview.get('total_records', 0):,}"],
                ['Time Period', overview.get('date_range', 'N/A')],
                ['Data Completeness', f"{overview.get('completeness_score', 0):.1f}%"]
            ]
            
            summary_table = Table(summary_data, colWidths=[3*inch, 3*inch])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3b82f6')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 10)
            ]))
            content.append(summary_table)
        
        content.append(PageBreak())
        return content
    
    def _build_overview_section(self, overview):
        """Build overview statistics section"""
        content = []
        
        content.append(Paragraph("1. Overview Statistics", self.styles['SectionHeader']))
        content.append(Spacer(1, 0.2*inch))
        
        # Basic stats table
        stats_data = [
            ['Statistic', 'Value'],
            ['Total Records', f"{overview.get('total_records', 0):,}"],
            ['Unique Emails', f"{overview.get('unique_emails', 0):,}"],
            ['Duplicate Rate', f"{overview.get('duplicate_rate', 0):.2f}%"],
            ['Date Range', overview.get('date_range', 'N/A')],
            ['Data Completeness', f"{overview.get('completeness_score', 0):.1f}%"]
        ]
        
        stats_table = Table(stats_data, colWidths=[3*inch, 3*inch])
        stats_table.setStyle(self._get_table_style())
        content.append(stats_table)
        content.append(Spacer(1, 0.3*inch))
        
        return content
    
    def _build_distributions_section(self, distributions):
        """Build distributions analysis section"""
        content = []
        
        content.append(Paragraph("2. Data Distributions", self.styles['SectionHeader']))
        content.append(Spacer(1, 0.2*inch))
        
        # Top domains
        if 'top_domains' in distributions:
            content.append(Paragraph("<b>Top Email Domains:</b>", self.styles['Metric']))
            domains = distributions['top_domains'][:10]
            
            domain_data = [['Domain', 'Count', 'Percentage']]
            for domain in domains:
                domain_data.append([
                    domain.get('domain', 'Unknown'),
                    f"{domain.get('count', 0):,}",
                    f"{domain.get('percentage', 0):.1f}%"
                ])
            
            domain_table = Table(domain_data, colWidths=[2.5*inch, 1.5*inch, 1.5*inch])
            domain_table.setStyle(self._get_table_style())
            content.append(domain_table)
            content.append(Spacer(1, 0.2*inch))
        
        # Amount distribution
        if 'amount_stats' in distributions:
            content.append(Paragraph("<b>Amount Statistics:</b>", self.styles['Metric']))
            stats = distributions['amount_stats']
            
            amount_data = [
                ['Statistic', 'Value'],
                ['Mean', f"${stats.get('mean', 0):.2f}"],
                ['Median', f"${stats.get('median', 0):.2f}"],
                ['Std Dev', f"${stats.get('std', 0):.2f}"],
                ['Min', f"${stats.get('min', 0):.2f}"],
                ['Max', f"${stats.get('max', 0):.2f}"]
            ]
            
            amount_table = Table(amount_data, colWidths=[2.5*inch, 2.5*inch])
            amount_table.setStyle(self._get_table_style())
            content.append(amount_table)
        
        content.append(Spacer(1, 0.3*inch))
        return content
    
    def _build_correlations_section(self, correlations):
        """Build fraud correlations section"""
        content = []
        
        content.append(Paragraph("3. Fraud Correlations", self.styles['SectionHeader']))
        content.append(Spacer(1, 0.2*inch))
        
        # High-risk patterns
        if 'high_risk_patterns' in correlations:
            content.append(Paragraph("<b>High-Risk Patterns Detected:</b>", self.styles['Metric']))
            patterns = correlations['high_risk_patterns']
            
            for pattern in patterns[:5]:
                pattern_text = f"• {pattern.get('description', 'N/A')}: <b>{pattern.get('count', 0):,} cases</b> ({pattern.get('percentage', 0):.1f}%)"
                content.append(Paragraph(pattern_text, self.styles['Normal']))
            
            content.append(Spacer(1, 0.2*inch))
        
        return content
    
    def _build_quality_section(self, quality_data):
        """Build data quality issues section"""
        content = []
        
        content.append(Paragraph("4. Data Quality Issues", self.styles['SectionHeader']))
        content.append(Spacer(1, 0.2*inch))
        
        issues = quality_data.get('issues', [])
        if issues:
            issue_data = [['Issue Type', 'Count', 'Severity']]
            for issue in issues[:10]:
                issue_data.append([
                    issue.get('type', 'Unknown'),
                    f"{issue.get('count', 0):,}",
                    issue.get('severity', 'Medium')
                ])
            
            issue_table = Table(issue_data, colWidths=[3*inch, 1.5*inch, 1.5*inch])
            issue_table.setStyle(self._get_table_style())
            content.append(issue_table)
        else:
            content.append(Paragraph("✓ No significant data quality issues detected.", self.styles['Normal']))
        
        content.append(Spacer(1, 0.3*inch))
        return content
    
    def _build_outliers_section(self, outliers):
        """Build outliers section"""
        content = []
        
        content.append(Paragraph("5. Statistical Outliers", self.styles['SectionHeader']))
        content.append(Spacer(1, 0.2*inch))
        
        outlier_list = outliers.get('outlier_records', [])
        if outlier_list:
            content.append(Paragraph(f"<b>Detected {len(outlier_list)} outlier records:</b>", self.styles['Metric']))
            
            outlier_data = [['Email', 'Amount', 'Reason']]
            for outlier in outlier_list[:10]:
                outlier_data.append([
                    outlier.get('email', 'N/A')[:30] + '...',
                    f"${outlier.get('amount', 0):.2f}",
                    outlier.get('reason', 'N/A')[:40]
                ])
            
            outlier_table = Table(outlier_data, colWidths=[2.5*inch, 1.5*inch, 2.5*inch])
            outlier_table.setStyle(self._get_table_style())
            content.append(outlier_table)
        else:
            content.append(Paragraph("✓ No statistical outliers detected.", self.styles['Normal']))
        
        return content
    
    def _get_table_style(self):
        """Get standard table style"""
        return TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3b82f6')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f3f4f6')),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#ffffff'), colors.HexColor('#f9fafb')])
        ])


# Example usage
if __name__ == '__main__':
    # Sample EDA results for testing
    sample_results = {
        'overview': {
            'total_records': 1500,
            'unique_emails': 1450,
            'duplicate_rate': 3.33,
            'date_range': '2024-01-01 to 2024-12-31',
            'completeness_score': 95.5
        },
        'distributions': {
            'top_domains': [
                {'domain': 'gmail.com', 'count': 800, 'percentage': 53.3},
                {'domain': 'yahoo.com', 'count': 300, 'percentage': 20.0},
                {'domain': 'outlook.com', 'count': 200, 'percentage': 13.3}
            ],
            'amount_stats': {
                'mean': 45.50,
                'median': 40.00,
                'std': 15.25,
                'min': 10.00,
                'max': 150.00
            }
        },
        'data_quality': {
            'issues': [
                {'type': 'Missing IP Address', 'count': 50, 'severity': 'Low'},
                {'type': 'Invalid Email Format', 'count': 10, 'severity': 'High'}
            ]
        },
        'outliers': {
            'outlier_records': [
                {'email': 'user1@example.com', 'amount': 500.00, 'reason': 'Amount > 3 std devs'},
                {'email': 'user2@example.com', 'amount': 450.00, 'reason': 'Unusual pattern'}
            ]
        }
    }
    
    generator = EDAReportGenerator()
    output = Path('reports/eda_sample_report.pdf')
    output.parent.mkdir(parents=True, exist_ok=True)
    
    generator.generate_pdf(sample_results, output, 'combined')
    print(f"✓ Sample PDF generated: {output}")
