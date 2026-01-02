import streamlit as st
import plotly.express as px
import pandas as pd
import numpy as np
from src.data_manager import DataManager

def render_analysis(data_manager: DataManager):
    st.header("Deep Analysis & Forecasting")
    
    df = data_manager.get_transactions()
    if df.empty:
        st.info("No data available.")
        return
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    df['month'] = df['date'].dt.month

    # Sidebar Filters
    st.sidebar.subheader("Analysis Filters")
    min_date = df['date'].min().date()
    max_date = df['date'].max().date()
    
    filter_mode = st.sidebar.radio("Analysis Period", ["All Time", "Year", "Month", "Custom"], key='ana_filter')
    
    filtered_df = df.copy()
    
    if filter_mode == "Year":
        selected_year = st.sidebar.selectbox("Select Year", sorted(df['year'].unique(), reverse=True), key='ana_year')
        filtered_df = df[df['year'] == selected_year]
        st.info(f"Analyzing data for Year: {selected_year}")
        
    elif filter_mode == "Month":
        selected_year = st.sidebar.selectbox("Select Year", sorted(df['year'].unique(), reverse=True), key='ana_year_m')
        selected_month = st.sidebar.selectbox("Select Month", range(1, 13), key='ana_month')
        filtered_df = df[(df['year'] == selected_year) & (df['month'] == selected_month)]
        st.info(f"Analyzing data for: {selected_month}/{selected_year}")
        
    elif filter_mode == "Custom":
        start_date = st.sidebar.date_input("Start Date", min_date, key='ana_start')
        end_date = st.sidebar.date_input("End Date", max_date, key='ana_end')
        if start_date <= end_date:
            filtered_df = df[(df['date'].dt.date >= start_date) & (df['date'].dt.date <= end_date)]
            st.info(f"Analyzing from {start_date} to {end_date}")
        else:
            st.error("Start date must be before end date.")

    # Tabs for different analysis views
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Smart Insights", "Income Analysis", "Tag Analysis", "Needs vs Wants", "Forecasting"])
    
    with tab1:
        render_smart_insights(filtered_df)

    with tab2:
        # Pass full df for historical context (Growth Rate), filtered_df for deep dive
        render_income_analysis(df, filtered_df)
        
    with tab3:
        render_tag_analysis(filtered_df)
        
    with tab4:
        render_needs_vs_wants(filtered_df)
        
    with tab5:
        # Forecasting usually needs more context than a small slice, 
        # but let's pass filtered_df. Users might select a year and want to see forecast at end of it.
        # Or better: Forecasting normally looks at LATEST data. 
        # If user selects "2020", forecasting "Next Month" (Jan 2021) is technically correct for that snapshot.
        render_forecasting(filtered_df)

def render_smart_insights(df):
    st.subheader("💡 Smart Savings Insights")
    
    # Filter expenses
    expenses = df[df['type'] == 'Expense'].copy()
    expenses['abs_amount'] = expenses['amount'].abs()
    
    if expenses.empty:
        st.write("No expenses to analyze.")
        return

    # 1. Top "Want" Categories
    if 'necessity' in expenses.columns:
        wants = expenses[expenses['necessity'] == 'Want']
        if not wants.empty:
            st.markdown("### 💸 Where can you save?")
            wants_by_cat = wants.groupby('category')['abs_amount'].sum().reset_index().sort_values('abs_amount', ascending=False)
            top_want = wants_by_cat.iloc[0]
            
            col1, col2 = st.columns([2, 1])
            with col1:
                st.write(f"Your biggest discretionary spending is **{top_want['category']}**.")
                st.bar_chart(wants_by_cat.set_index('category').head(5))
            with col2:
                total_wants = wants['abs_amount'].sum()
                savings_potential = total_wants * 0.20 # 20% cut rule
                st.metric("Total 'Wants' (All Time)", f"€{total_wants:,.0f}")
                st.success(f"Trim 20%? Save **€{savings_potential:,.0f}**!")
    
    st.divider()
    
    # 2. Monthly Anomalies (Z-Score or Deviation)
    st.markdown("### 📈 Monthly Anomalies")
    expenses['month_year'] = expenses['date'].dt.to_period('M')
    monthly_cat = expenses.groupby(['month_year', 'category'])['abs_amount'].sum().reset_index()
    
    # Last month
    last_month = expenses['month_year'].max()
    last_month_data = monthly_cat[monthly_cat['month_year'] == last_month]
    
    # Average excluding last month
    historical = monthly_cat[monthly_cat['month_year'] < last_month]
    avg_cat = historical.groupby('category')['abs_amount'].mean().reset_index()
    
    merged = pd.merge(last_month_data, avg_cat, on='category', suffixes=('_curr', '_avg'))
    merged['diff'] = merged['abs_amount_curr'] - merged['abs_amount_avg']
    merged['pct_change'] = (merged['diff'] / merged['abs_amount_avg']) * 100
    
    # Alert on significant increases (> 20% and > €50)
    alerts = merged[(merged['pct_change'] > 20) & (merged['diff'] > 50)].sort_values('diff', ascending=False)
    
    if not alerts.empty:
        st.warning(f"⚠️ High spending alerts for **{last_month}**:")
        for _, row in alerts.iterrows():
            st.write(f"- **{row['category']}**: €{row['abs_amount_curr']:,.2f} (+{row['pct_change']:.1f}% vs avg)")
    else:
        st.success(f"✅ Good job! No significant overspending detected in **{last_month}**.")

def render_tag_analysis(df):
    st.subheader("Tag Analysis")
    # ... (rest of tag analysis code)
    # Explode tags
    df_transactions = df.copy() # Use copy for operations
    df_tags = df_transactions.explode('tags')
    # Filter empty tags: handle list/array/string
    # Ensure tags are strings
    df_tags['tags'] = df_tags['tags'].astype(str)
    df_tags = df_tags[df_tags['tags'] != 'nan']
    df_tags = df_tags[df_tags['tags'] != '']
    df_tags = df_tags[df_tags['tags'] != 'None'] 
    
    if not df_tags.empty:
        all_tags = sorted(df_tags['tags'].unique())
        selected_tag = st.selectbox("Select Tag to Analyze", all_tags)
        
        if selected_tag:
            tag_data = df_tags[df_tags['tags'] == selected_tag]
            
            # Metrics
            total_tag = tag_data['amount'].sum()
            avg_tag = tag_data['amount'].mean()
            count_tag = len(tag_data)
            
            cols = st.columns(3)
            cols[0].metric(f"Total {selected_tag}", f"€{total_tag:,.2f}")
            cols[1].metric("Average", f"€{avg_tag:,.2f}")
            cols[2].metric("Count", str(count_tag))
            
            # Chart
            fig_tag = px.bar(tag_data, x='date', y='amount', title=f"Spending history for {selected_tag}")
            st.plotly_chart(fig_tag, use_container_width=True)
    else:
        st.info("No tags found in data.")

def render_needs_vs_wants(df):
    st.subheader("Needs vs Wants")
    if 'necessity' in df.columns:
        # Group by Month and Necessity
        # Ensure date is datetime
        df['date'] = pd.to_datetime(df['date'])
        # Use ME instead of M for future warning fix
        df['month_year'] = df['date'].dt.to_period('M').astype(str)
        # Filter Expenses only
        expenses = df[df['type'] == 'Expense'].copy()
        expenses['abs_amount'] = expenses['amount'].abs()
        
        nw_grouped = expenses.groupby(['month_year', 'necessity'])['abs_amount'].sum().reset_index()
        
        fig_nw = px.bar(nw_grouped, x='month_year', y='abs_amount', color='necessity', 
                        title="Needs vs Wants over Time", barmode='stack',
                        category_orders={"necessity": ["Need", "Want"]})
        st.plotly_chart(fig_nw, use_container_width=True)
    else:
        st.warning("Necessity data not found. Please re-import data to apply new rules.")

def render_forecasting(df):
    st.subheader("Forecasting (Simple Moving Average)")
    
    # Calculate monthly totals
    # Use ME alias for compatibility if pandas is new, or M if older. 
    # Let's try 'ME' as suggested by warnings, or suppress warning.
    # Grouping key must be datetime
    df['date'] = pd.to_datetime(df['date'])
    monthly_totals = df[df['type'] == 'Expense'].groupby(pd.Grouper(key='date', freq='ME'))['amount'].sum().abs()
    
    if len(monthly_totals) >= 3:
        last_3_avg = monthly_totals.iloc[-3:].mean()
        last_month_val = monthly_totals.iloc[-1]
        
        st.metric("3-Month Average Expense", f"€{last_3_avg:,.2f}")
        st.metric("Last Month Expense", f"€{last_month_val:,.2f}")
        
        prediction = last_3_avg
        st.info(f"Predicted Expense for Next Month: €{prediction:,.2f}")
        
        # Chart with prediction
        forecast_df = monthly_totals.reset_index()
        forecast_df.columns = ['date', 'amount']
        
        # Add next month
        next_month = forecast_df['date'].iloc[-1] + pd.DateOffset(months=1)
        new_row = pd.DataFrame({'date': [next_month], 'amount': [prediction], 'type': ['Forecast']})
        forecast_df['type'] = 'Actual'
        
        combined = pd.concat([forecast_df, new_row], ignore_index=True)
        
        fig_forecast = px.line(combined, x='date', y='amount', color='type', markers=True, title="Expense Forecast")
        st.plotly_chart(fig_forecast, use_container_width=True)
        
    else:
        st.write("Not enough data for forecasting (need at least 3 months).")

def render_income_analysis(full_df, filtered_df):
    st.subheader("💰 Income Analysis")
    
    # Use full data for trends
    full_income = full_df[full_df['type'] == 'Income'].copy()
    
    if full_income.empty:
        st.info("No income data found.")
        return

    # 1. Monthly Average (All Time vs Selected Period)
    # Use grouped by ME if newer pandas, or M if older and you want to suppress warnings or just stick to what works.
    # The warning said 'M' is deprecated, use 'ME'.
    monthly_inc_all = full_income.groupby(pd.Grouper(key='date', freq='ME'))['amount'].sum()
    avg_monthly_all = monthly_inc_all.mean()
    
    # Filtered stats
    filtered_income = filtered_df[filtered_df['type'] == 'Income']
    total_period = filtered_income['amount'].sum()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Avg Monthly Income (All Time)", f"€{avg_monthly_all:,.2f}")
    col2.metric("Total Income (Selected Period)", f"€{total_period:,.2f}")
    
    # 2. Annual Growth Rate (CAGR or YoY)
    st.markdown("### 📈 Growth & Trends")
    
    # Annual totals
    annual_inc = full_income.groupby(full_income['date'].dt.year)['amount'].sum()
    
    # Determine which years to compare
    # Check if filtered_df has a specific year selected
    selected_years = filtered_df['date'].dt.year.unique()
    
    target_year = None
    if len(selected_years) == 1:
        target_year = selected_years[0]
    else:
        # Default to latest year in full dataset if multiple selected
        if not annual_inc.empty:
            target_year = annual_inc.index.max()

    if target_year and (target_year - 1) in annual_inc.index:
        current_val = annual_inc[target_year]
        prev_val = annual_inc[target_year - 1]
        
        growth_pct = ((current_val - prev_val) / prev_val) * 100
        col3.metric(f"Growth ({target_year - 1} vs {target_year})", f"{growth_pct:+.1f}%")
    else:
        if target_year:
            col3.info(f"No data for {target_year - 1} to compare.")
        else:
            col3.info("Select a single year to see growth.")
            
    # Chart: Annual Trend
    fig_annual = px.bar(x=annual_inc.index, y=annual_inc.values, title="Annual Income Trend", labels={'x': 'Year', 'y': 'Total Income'})
    st.plotly_chart(fig_annual, use_container_width=True)

    st.divider()

    # 3. Income Sources Decomposition
    st.markdown("### 🏦 Income Sources")
    if not filtered_income.empty:
        # Pie chart of categories
        inc_by_cat = filtered_income.groupby('category')['amount'].sum().reset_index()
        fig_pie = px.pie(inc_by_cat, values='amount', names='category', title="Income Mix (Selected Period)", hole=0.4)
        
        # Trend of sources over time
        # Stacked bar
        monthly_cat = filtered_income.groupby([pd.Grouper(key='date', freq='ME'), 'category'])['amount'].sum().reset_index()
        fig_stack = px.bar(monthly_cat, x='date', y='amount', color='category', title="Income Sources over Time")
        
        c1, c2 = st.columns(2)
        c1.plotly_chart(fig_pie, use_container_width=True)
        c2.plotly_chart(fig_stack, use_container_width=True)
