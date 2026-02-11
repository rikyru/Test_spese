import streamlit as st
import plotly.express as px
import pandas as pd
import plotly.graph_objects as go
from src.data_manager import DataManager
import datetime
from src.ui.styling import get_chart_colors
from src.rules_engine import RulesEngine

def render_dashboard(data_manager):
    st.header("Dashboard v2.0")
    
    # Load rules for icons
    re = RulesEngine("d:/Test_spese/rules.yaml") # Should probably inject this, but direct load is fine
    wallet_rules = re.rules.get('wallets', {})
    
    try:
        df = data_manager.get_transactions()
        if df.empty:
            st.info("No data available. Please import a ZIP file.")
            return

        # Ensure date is datetime
        df['date'] = pd.to_datetime(df['date'])
        df['year'] = df['date'].dt.year
        df['month'] = df['date'].dt.month

        # Sidebar Filters
        st.sidebar.subheader("Filters")
        
        # Date Filter
        min_date = df['date'].min().date()
        max_date = df['date'].max().date()
        
        filter_mode = st.sidebar.radio("Period", ["Year", "Month", "Custom", "All Time"], index=1)
        
        filtered_df = df.copy()
        
        if filter_mode == "Year":
            selected_year = st.sidebar.selectbox("Select Year", sorted(df['year'].unique(), reverse=True))
            filtered_df = df[df['year'] == selected_year]
            st.caption(f"Showing data for Year: {selected_year}")
            
        elif filter_mode == "Month":
            # Default to current month if logical
            today = datetime.date.today()
            default_month_idx = today.month - 1
            
            # Years: Union of DB years and Current Year
            available_years = sorted(list(set(df['year'].unique()) | {today.year}), reverse=True)
            
            # Default index: try to find today.year
            default_year_idx = 0
            if today.year in available_years:
                default_year_idx = available_years.index(today.year)
            
            selected_year = st.sidebar.selectbox("Select Year", available_years, index=default_year_idx)
            selected_month = st.sidebar.selectbox("Select Month", range(1, 13), index=default_month_idx)
            filtered_df = df[(df['year'] == selected_year) & (df['month'] == selected_month)]
            st.caption(f"Showing data for: {selected_month}/{selected_year}")
            
        elif filter_mode == "Custom":
            start_date = st.sidebar.date_input("Start Date", min_date)
            end_date = st.sidebar.date_input("End Date", max_date)
            if start_date <= end_date:
                filtered_df = df[(df['date'].dt.date >= start_date) & (df['date'].dt.date <= end_date)]
            else:
                st.error("Start date must be before end date.")
        
        # --- 0. Liquidity Overview (New) ---
        st.divider()
        st.subheader("💳 Wallet & Liquidity")
        
        # We must operate on the FULL dataset for liquidity (cumulative balance)
        full_df = df # df is already full get_transactions() result
        

        if not full_df.empty:
            # Calculate balance per account
            balances = full_df.groupby('account')['amount'].sum().reset_index()
            total_liquidity = balances['amount'].sum()
            
            # --- Total Liquidity Big Card ---
            st.markdown(f"""
            <div style="padding: 20px; border-radius: 10px; background: linear-gradient(90deg, #4CAF50 0%, #2E7D32 100%); color: white; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                <h3 style="margin:0; font-size: 1.2rem; opacity: 0.9;">Total Liquidity</h3>
                <h1 style="margin:0; font-size: 2.5rem;">€ {total_liquidity:,.2f}</h1>
            </div>
            """, unsafe_allow_html=True)
            
            # --- Wallet Grid ---
            if not balances.empty:
                st.write("##### Active Wallets")
                
                # Helper for icons
                def get_icon(name):
                    # Check custom rule first
                    if name in wallet_rules and 'icon' in wallet_rules[name]:
                        return wallet_rules[name]['icon']
                        
                    name = name.lower()
                    if any(x in name for x in ['contanti', 'cash', 'tasca']): return "💵"
                    if any(x in name for x in ['banca', 'bank', 'unicredit', 'intesa', 'bnl', 'posta', 'conto']): return "🏦"
                    if any(x in name for x in ['revolut', 'paypal', 'satispay', 'visa', 'mastercard', 'amex']): return "💳"
                    if any(x in name for x in ['risparmi', 'fondo', 'deposito', 'salvadanaio']): return "🐷"
                    if any(x in name for x in ['invest', 'trade', 'crypto', 'bitcoin']): return "📈"
                    return "👛"

                # Create rows of 3
                cols = st.columns(3)
                for i, row in balances.iterrows():
                    acc_name = row['account']
                    bal = row['amount']
                    icon = get_icon(acc_name)
                    
                    # Determine color for amount
                    color = "#2E7D32" if bal >= 0 else "#C62828"
                    
                    with cols[i % 3]:
                        with st.container(border=True):
                            st.markdown(f"**{icon} {acc_name}**")
                            st.markdown(f"<h3 style='margin:0; color: {color};'>€ {bal:,.2f}</h3>", unsafe_allow_html=True)

        # --- Metrics ---
        st.divider()
        total_income = filtered_df[filtered_df['type'] == 'Income']['amount'].sum()
        total_expense = filtered_df[filtered_df['type'] == 'Expense']['amount'].sum()
        balance = total_income + total_expense
        savings_rate = (balance / total_income * 100) if total_income > 0 else 0

        # Projections (If Month Mode)
        projected_msg = ""
        projected_balance = balance
        
        if filter_mode == "Month":
            from datetime import date
            # Calculate end of selected month
            import calendar
            last_day = calendar.monthrange(selected_year, selected_month)[1]
            end_of_period = date(selected_year, selected_month, last_day)
            
            # Get projections up to end of month
            proj_df = data_manager.get_projected_recurring(end_of_period)
            
            if not proj_df.empty:
                # Sum expenses (negative amounts)
                # Ensure we only count those strictly AFTER current max date in data might be safer,
                # but get_projected_recurring uses next_date which is naturally future.
                # Just filter strictly within the month just in case next_date jumps out?
                # The method returns until end_date so it's fine.
                
                proj_expenses = proj_df[proj_df['amount'] < 0]['amount'].sum()
                if proj_expenses < 0:
                     projected_balance += proj_expenses
                     projected_msg = f"📉 Includes €{abs(proj_expenses):.2f} pending recurring"

        # --- Recurring Expenses Impact ---
        # Get monthly recurring total
        rec_df = data_manager.get_recurring()
        total_recurring_monthly = 0.0
        
        if not rec_df.empty:
            # Normalize to monthly amount
            def to_monthly(row):
                amt = row['amount']
                freq = row['frequency'] 
                if freq == 'Monthly': return amt
                if freq == 'Yearly': return amt / 12
                if freq == 'Weekly': return amt * 4.33
                return amt
            
            total_recurring_monthly = rec_df.apply(to_monthly, axis=1).sum()
            
        # Disposable Income (Assuming average monthly income or current month income)
        # For meaningful "Budget", we should use the Income of the selected period if it's a month, 
        # or an average. Let's use the current selected period's income.
        
        disposable_income = total_income + total_recurring_monthly # recurring is negative usually
        # Wait, total_income includes everything? No, total_income is just Income.
        # "Disposable" usually means "Income - Fixed Expenses".
        # So: Real Disposable = Income - abs(Fixed Expenses)
        # But Fixed Expenses might already be in "total_expense" if they happened?
        # Yes, but we want to show "Committed" vs "Free".
        
        # Metric: "Monthly Fixed Commitment"
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Income", f"€{total_income:,.2f}")
        col2.metric("Expenses", f"€{total_expense:,.2f}", delta_color="inverse")
        col3.metric("Net Balance", f"€{balance:,.2f}", help="Current Actual Balance")
        
        # New Metric: Disposable / Free
        # If we are in a specific month, we can project.
        # Let's show "Recurring Commitment"
        col4.metric("Est. Recurring/Mo", f"€{total_recurring_monthly:,.2f}", help="Estimated monthly fixed expenses based on active recurring templates.")
        
        if filter_mode == "Month":
             # Show progress bar for budget?
             # "Free to Spend"
             # Est. Income (take current) + Est. Recurring (negative)
             # Remaining = Income - abs(Recurring) - abs(Variable Expenses)
             # But Variable Expenses = Total Expenses - (Expenses that matched Recurring)
             # Hard to separate exactly without linking transaction to recurring rule.
             # Simplified:
             # Free Cash Flow = Income - abs(Recurring)
             free_cash = total_income + total_recurring_monthly
             
             # --- Budget / Safe to Spend Logic ---
             
             # Calculate Pending Recurring for this month
             # We already have `projected_msg` logic earlier, let's reuse/refine.
             from datetime import date
             import calendar
             last_day = calendar.monthrange(selected_year, selected_month)[1]
             end_of_period = date(selected_year, selected_month, last_day)
             
             # Get projections up to end of month
             # Note: get_projected_recurring returns negative amounts for expenses
             proj_df = data_manager.get_projected_recurring(end_of_period)
             pending_recurring = 0.0
             if not proj_df.empty:
                 pending_recurring = proj_df[proj_df['amount'] < 0]['amount'].sum()
             
             # "Safe/Free to Spend" = Current Balance - abs(Pending Recurring)
             # Because Balance includes everything paid so far.
             # Pending are things we MUST pay.
             safe_to_spend = balance + pending_recurring # pending is negative
             
             # Visual Card
             st.markdown("### 💡 Monthly Budget Insight")
             
             # Create a 3-column visuals
             b_col1, b_col2, b_col3 = st.columns(3)
             
             with b_col1:
                 st.metric("Current Balance", f"€{balance:,.2f}", help="Income - Expenses So Far")
                 
             with b_col2:
                 st.metric("🔒 Upcoming Fixed", f"€{abs(pending_recurring):,.2f}", help="Recurring expenses due before end of month")
                 
             with b_col3:
                 # Color logic
                 safe_color = "normal"
                 if safe_to_spend < 0: safe_color = "inverse"
                 st.metric("💸 Safe to Spend", f"€{safe_to_spend:,.2f}", delta=f"{safe_to_spend:,.2f}", delta_color=safe_color, help="Balance - Upcoming Fixed. This is what you can spend on variable costs.")
             
             # Progress Bar for Fixed Costs Coverage?
             # Total Recurring for month
             total_fixed_est = abs(total_recurring_monthly)
             # How much fixed paid? Hard to know exactly without matching.
             # But we can show: Income vs (Fixed + Variable)
             
             st.caption(f"Estimated Total Fixed Costs for Month: €{total_fixed_est:,.2f}")

        # --- Visualizations ---
        
        # 1. Income vs Expense Breakdown
        col_charts_1, col_charts_2 = st.columns(2)
        
        with col_charts_1:
            st.subheader("Income Sources")
            income_df = filtered_df[filtered_df['type'] == 'Income']
            if not income_df.empty:
                # Group by Category if available, else Description
                # Usually Income has fewer categories.
                income_by_cat = income_df.groupby('category')['amount'].sum().reset_index()
                fig_inc = px.pie(income_by_cat, values='amount', names='category', hole=0.4)
                st.plotly_chart(fig_inc, use_container_width=True)
            else:
                st.info("No income data for this period.")

        with col_charts_2:
            st.subheader("Expense Categories")
            expense_df = filtered_df[filtered_df['type'] == 'Expense']
            if not expense_df.empty:
                # Use absolute values for charts
                expense_df = expense_df.copy()
                expense_df['abs_amount'] = expense_df['amount'].abs()
                
                exp_by_cat = expense_df.groupby('category')['abs_amount'].sum().reset_index().sort_values('abs_amount', ascending=False)
                fig_exp = px.pie(exp_by_cat, values='abs_amount', names='category', hole=0.4)
                st.plotly_chart(fig_exp, use_container_width=True)
            else:
                st.info("No expense data for this period.")

        # 2. Year over Year Comparison (Only if Year mode is selected or generally useful)
        st.subheader("Year over Year Comparison (Monthly Expenses)")
        
        # Prepare data for all time to do YoY
        expense_all = df[df['type'] == 'Expense'].copy()
        expense_all['abs_amount'] = expense_all['amount'].abs()
        
        # Pivot: index=Month, columns=Year, values=Sum
        yoy_data = expense_all.groupby(['month', 'year'])['abs_amount'].sum().unstack(fill_value=0)
        
        if not yoy_data.empty:
            fig_yoy = px.line(yoy_data, x=yoy_data.index, y=yoy_data.columns, markers=True, 
                              labels={'value': 'Amount (€)', 'month': 'Month', 'variable': 'Year'})
            st.plotly_chart(fig_yoy, use_container_width=True)

        # 3. Monthly Balance Trend (Combo Chart)
        st.subheader("Monthly Balance Trend")
        
        # Prepare data for all time (or filtered range if user wants, but Trend is usually best over time)
        # Using filtered_df if "Month" filter is NOT active makes sense.
        # If "Month" is active, maybe show Daily trend? 
        # User requested "Monthly balance", so let's stick to Monthly aggregation of the full or filtered dataset.
        
        trend_source = df if filter_mode == "Month" else filtered_df # If in Month view, show everything for context? Or logic:
        # If User selected "Year 2024", show months of 2024.
        # If User selected "All Time", show all months.
        # If User selected "Month", show daily??? No, user asked for "Month by Month".
        # So if they are in "Month" view, this chart might be static single point?
        # Let's use the 'df' (full data) filtered by the selected Year if in Year mode, or just full df for context.
        # Actually standard behavior: Dashboard charts usually reflect filters. But "Trend" implies time series.
        # If in "Month" view, let's show Daily trend for that month instead?
        # User asked: "grafico del saldo mese per mese che ora manca". This implies a Year/AllTime view.
        
        chart_data = filtered_df.copy()
        if filter_mode == "Month":
             # In Month mode, showing "Month by Month" is one bar. 
             # Let's switch to show the whole Year of the selected month to give context?
             # Or show Daily for that month.
             # Implem: If Month mode, show Daily. If Year/AllTime, show Monthly.
             pass
        
        # We'll implement Monthly View for Year/AllTime, and Daily for Month mode.
        
        if filter_mode == "Month":
            # Daily Trend
            st.caption("Daily Trend for selected month")
            try:
                # Use pivot_table for safety
                daily_df = filtered_df.copy()
                daily_df['day_date'] = daily_df['date'].dt.date
                
                if not daily_df.empty:
                    grp = daily_df.pivot_table(index='day_date', columns='type', values='amount', aggfunc='sum', fill_value=0)
                    
                    if 'Income' not in grp.columns: grp['Income'] = 0.0
                    if 'Expense' not in grp.columns: grp['Expense'] = 0.0
                    
                    grp['Balance'] = grp['Income'] + grp['Expense']
                    grp['Cumulative'] = grp['Balance'].cumsum()
                    
                    daily_stats = grp.reset_index()
                    # daily_stats has 'day_date' as column now
                    
                    if not daily_stats.empty:
                        fig_daily = go.Figure()
                        
                        fig_daily.add_trace(go.Bar(x=daily_stats['day_date'], y=daily_stats['Income'], name='Daily Income', marker_color='#4CAF50', opacity=0.6))
                        fig_daily.add_trace(go.Bar(x=daily_stats['day_date'], y=daily_stats['Expense'], name='Daily Expenses', marker_color='#EF5350', opacity=0.6))
                        
                        fig_daily.add_trace(go.Scatter(x=daily_stats['day_date'], y=daily_stats['Cumulative'], name='Month Cashflow', mode='lines+markers', line=dict(color='#2196F3', width=3)))
                        
                        fig_daily.update_layout(
                            title="Daily Cashflow & Trend",
                            barmode='overlay',
                            xaxis_title="Date",
                            yaxis_title="Amount (€)",
                            hovermode="x unified",
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                        )
                        st.plotly_chart(fig_daily, use_container_width=True)
                    else:
                        st.info("No data for daily trend.")
                else:
                    st.info("No data for daily trend.")
            except Exception as e:
                st.error(f"Error showing daily trend: {e}")

        if filter_mode != "Month": 
            # Group by Month-Year
            try:
                trend_df = filtered_df.copy()
                trend_df['month_date'] = trend_df['date'].apply(lambda d: d.replace(day=1))
                
                if not trend_df.empty:
                    # Safe Pivot
                    grp = trend_df.pivot_table(index='month_date', columns='type', values='amount', aggfunc='sum', fill_value=0)
                    
                    if 'Income' not in grp.columns: grp['Income'] = 0.0
                    if 'Expense' not in grp.columns: grp['Expense'] = 0.0
                    
                    grp['Balance'] = grp['Income'] + grp['Expense']
                    
                    monthly_stats = grp.reset_index()
                    
                    if not monthly_stats.empty:
                        st.subheader("Monthly Balance Trend")
                        fig_combo = go.Figure()
                        fig_combo.add_trace(go.Bar(x=monthly_stats['month_date'], y=monthly_stats['Income'], name='Income', marker_color='#4CAF50'))
                        fig_combo.add_trace(go.Bar(x=monthly_stats['month_date'], y=monthly_stats['Expense'], name='Expenses', marker_color='#EF5350'))
                        fig_combo.add_trace(go.Scatter(x=monthly_stats['month_date'], y=monthly_stats['Balance'], name='Net Balance', mode='lines+markers', line=dict(color='#2196F3', width=3), marker=dict(size=8)))
                        
                        fig_combo.update_layout(title="Monthly Income, Expenses & Balance", barmode='overlay', xaxis_title="Month", yaxis_title="Amount (€)", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), hovermode="x unified")
                        st.plotly_chart(fig_combo, use_container_width=True)
                    else:
                        st.info("No data for trend.")
                else:
                    st.info("No data for trend.")
            except Exception as e:
                st.error(f"Error showing trend: {e}")
                
            # Net Worth Chart
            st.subheader("📈 Total Net Worth Evolution")
            try:
                nw_df = df.sort_values('date').copy()
                nw_df['cumulative_balance'] = nw_df['amount'].cumsum()
                
                if filter_mode == "Year":
                     start_of_year = pd.Timestamp(selected_year, 1, 1).date()
                     end_of_year = pd.Timestamp(selected_year, 12, 31).date()
                     chart_nw = nw_df[(nw_df['date'].dt.date >= start_of_year) & (nw_df['date'].dt.date <= end_of_year)]
                elif filter_mode == "Custom":
                     chart_nw = nw_df[(nw_df['date'].dt.date >= start_date) & (nw_df['date'].dt.date <= end_date)]
                else: 
                     chart_nw = nw_df
                
                if not chart_nw.empty:
                    daily_nw = chart_nw.groupby('date')['cumulative_balance'].last().reset_index()
                    fig_nw = px.area(daily_nw, x='date', y='cumulative_balance', title="Total Net Worth Over Time", labels={'cumulative_balance': 'Net Worth (€)'})
                    fig_nw.update_layout(hovermode="x unified")
                    fig_nw.update_traces(line_color='#009688', fillcolor='rgba(0, 150, 136, 0.3)')
                    st.plotly_chart(fig_nw, use_container_width=True)
            except Exception as e:
                st.error(f"Error calculating net worth: {e}")
        
        else:
             # Yearly Context in Month Mode
             st.subheader("Yearly Context")
             try:
                 year_df = df[df['year'] == selected_year].copy()
                 year_df['month_date'] = year_df['date'].apply(lambda d: d.replace(day=1))
                 
                 if not year_df.empty:
                     grp = year_df.pivot_table(index='month_date', columns='type', values='amount', aggfunc='sum', fill_value=0)
                     
                     if 'Income' not in grp.columns: grp['Income'] = 0.0
                     if 'Expense' not in grp.columns: grp['Expense'] = 0.0
                     
                     grp['Balance'] = grp['Income'] + grp['Expense']
                     
                     monthly_stats = grp.reset_index()
                     
                     if not monthly_stats.empty:
                         fig_combo = go.Figure()
                         fig_combo.add_trace(go.Bar(x=monthly_stats['month_date'], y=monthly_stats['Income'], name='Income', marker_color='#4CAF50'))
                         fig_combo.add_trace(go.Bar(x=monthly_stats['month_date'], y=monthly_stats['Expense'], name='Expenses', marker_color='#EF5350'))
                         fig_combo.add_trace(go.Scatter(x=monthly_stats['month_date'], y=monthly_stats['Balance'], name='Net Balance', mode='lines+markers', line=dict(color='#2196F3', width=3)))
                         
                         fig_combo.update_layout(title=f"Overview {selected_year}", barmode='relative', hovermode="x unified")
                         st.plotly_chart(fig_combo, use_container_width=True)
                 else:
                     st.info("No data for yearly context.")
             except Exception as e:
                 st.error(f"Error showing yearly context: {e}")

        st.divider()

        # 5. Clear Data Tables
        st.subheader("📊 Detailed Breakdowns")
        
        col_breakdown_1, col_breakdown_2 = st.columns(2)
        
        expense_df = filtered_df[filtered_df['type'] == 'Expense'].copy()
        if not expense_df.empty:
            expense_df['abs_amount'] = expense_df['amount'].abs()
        
        with col_breakdown_1:
            st.write("### Expenses by Category")
            if not expense_df.empty:
                cat_summary = expense_df.groupby('category')['abs_amount'].sum().reset_index()
                cat_summary = cat_summary.sort_values('abs_amount', ascending=False)
                cat_summary['% Total'] = (cat_summary['abs_amount'] / cat_summary['abs_amount'].sum()) * 100
                
                # Format for display
                cat_summary['Display Amount'] = cat_summary['abs_amount'].apply(lambda x: f"€{x:,.2f}")
                cat_summary['% Total'] = cat_summary['% Total'].apply(lambda x: f"{x:.1f}%")
                
                st.dataframe(
                    cat_summary[['category', 'Display Amount', '% Total']], 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={"category": "Category", "Display Amount": "Amount"}
                )
            else:
                st.info("No expenses.")

        with col_breakdown_2:
            st.write("### Expenses by Tag")
            if not expense_df.empty:
                # Explode tags
                tag_df = expense_df.explode('tags')
                # Clean tags (remove None, nan, empty strings)
                tag_df['tags'] = tag_df['tags'].astype(str)
                tag_df = tag_df[~tag_df['tags'].isin(['nan', 'None', '', 'nan'])]
                
                if not tag_df.empty:
                    tag_summary = tag_df.groupby('tags')['abs_amount'].sum().reset_index()
                    tag_summary = tag_summary.sort_values('abs_amount', ascending=False)
                    # Note: % Total for tags might exceed 100% of total expenses if multiple tags per transaction?
                    # But usually we want % of total expenses involving this tag.
                    # Or % of total spending? Let's do % of total spending derived from the original df sum.
                    total_sepnding = expense_df['abs_amount'].sum()
                    tag_summary['% Total'] = (tag_summary['abs_amount'] / total_sepnding) * 100
                    
                    # Format
                    tag_summary['Display Amount'] = tag_summary['abs_amount'].apply(lambda x: f"€{x:,.2f}")
                    tag_summary['% Total'] = tag_summary['% Total'].apply(lambda x: f"{x:.1f}%")
                    
                    st.dataframe(
                        tag_summary[['tags', 'Display Amount', '% Total']], 
                        use_container_width=True, 
                        hide_index=True,
                        column_config={"tags": "Tag", "Display Amount": "Amount"}
                    )
                else:
                    st.info("No tagged expenses.")
            else:
                st.info("No expenses.")
        
        st.write("### Top Transactions")
        # Show top 10 largest expenses
        if not expense_df.empty:
            top_expenses = expense_df.sort_values('abs_amount', ascending=False).head(10)
            
            display_cols = top_expenses[['date', 'description', 'category', 'tags', 'amount']]
            st.dataframe(
                display_cols.style.format({'amount': '€{:.2f}'}), 
                use_container_width=True, 
                hide_index=True
            )
        else:
            st.info("No transactions.")

        # 4. Detailed Transaction List (Optional toggle)
        with st.expander("View All Transactions in this Period"):
            st.dataframe(filtered_df.sort_values('date', ascending=False), use_container_width=True)

    except Exception as e:
        st.error(f"Error loading dashboard: {e}")
        import traceback
        st.text(traceback.format_exc())
