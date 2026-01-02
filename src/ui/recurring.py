import streamlit as st
import pandas as pd
from src.data_manager import DataManager

def render_recurring(data_manager: DataManager):
    st.title("🔁 Recurring Expenses (Spese Fisse)")
    
    # --- Action Section ---
    col_act_1, col_act_2 = st.columns([3, 1])
    with col_act_1:
        st.info("Manage your fixed expenses here. The system will automatically generate transactions when they are due.")
    
    with col_act_2:
        if st.button("🔄 Check & Generate Due", type="primary", use_container_width=True):
            with st.spinner("Checking due expenses..."):
                count = data_manager.process_recurring()
                if count > 0:
                    st.success(f"Generated {count} transactions!")
                    st.toast(f"Generated {count} transactions!", icon="✅")
                    # Optional: st.rerun() if we want to show them immediately in a log, but not strictly needed here
                else:
                    st.info("No expenses due today.")
                    st.toast("No expenses due today.", icon="ℹ️")

    # --- Upcoming Projections Section ---
    from datetime import date, timedelta
    
    st.subheader("📅 Upcoming in next 30 days")
    
    # Get projections for next 30 days
    today = date.today()
    next_30 = today + timedelta(days=30)
    
    proj_idx = data_manager.get_projected_recurring(next_30)
    
    if not proj_idx.empty:
        # Sort by date
        proj_idx = proj_idx.sort_values('date')
        
        # Display nicely
        
        # Summary metrics
        total_p = proj_idx[proj_idx['amount'] < 0]['amount'].sum()
        st.caption(f"Total scheduled expenses: **€{total_p:,.2f}**")
        
        # Cards
        for i, row in proj_idx.iterrows():
            days_left = (row['date'] - today).days
            
            # Color coding
            if days_left < 0:
                 status = "⚠️ OVERDUE"
                 color = "#FFCDD2" # Red Light
            elif days_left == 0:
                 status = "🔥 TODAY"
                 color = "#FFF9C4" # Yellow Light
            elif days_left <= 7:
                 status = f"⏰ In {days_left} days"
                 color = "#E1F5FE" # Blue Light
            else:
                 status = f"🗓 In {days_left} days"
                 color = "#F5F5F5" # Grey
            
            with st.container():
                st.markdown(f"""
                <div style="background-color: {color}; padding: 10px; border-radius: 8px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between;">
                    <div style="flex-grow: 1;">
                        <span style="font-weight: bold; font-size: 1.1em; color: #333;">{row['name']}</span>
                         <br><span style="font-size: 0.9em; color: #666;">{row['date'].strftime('%d %b %Y')} ({row['frequency']})</span>
                    </div>
                    <div style="text-align: right;">
                        <span style="font-weight: bold; color: {'red' if row['amount'] < 0 else 'green'}; font-size: 1.1em;">€{row['amount']:.2f}</span>
                        <br><span style="font-size: 0.85em; font-weight: bold; color: #555;">{status}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
    else:
        st.info("No recurring expenses scheduled for the next 30 days.")
        
    st.divider()

    # --- Add New Recurring ---
    st.subheader("➕ Add New Template")
    
    with st.expander("Create New Recurring Expense", expanded=True):
        with st.form("add_rec_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                r_name = st.text_input("Template Name", placeholder="e.g. Netflix Subscription")
                r_amount = st.number_input("Amount (Negative for Expense)", value=-10.0, step=1.0, help="Use negative values for expenses, positive for income.")
                r_cat = st.selectbox("Category", data_manager.get_unique_categories() + ["Other"])
                if r_cat == "Other":
                   r_cat_custom = st.text_input("New Category Name")
                   r_cat = r_cat_custom if r_cat_custom else "General"
                   
            with col2:
                r_acc = st.selectbox("Account/Wallet", data_manager.get_unique_accounts())
                r_freq = st.selectbox("Frequency", ["Monthly", "Weekly", "Yearly"])
                r_date = st.date_input("Next Due Date")



            # Limits / Termination
            st.markdown("#### Duration limits (Optional)")
            r_duration_type = st.radio("Stop condition", ["Indefinite (Forever)", "Fixed Installments (Rate)", "Until Date (Ends on)"], horizontal=True, index=0)
            
            r_installments = None
            r_end_date = None
            
            if r_duration_type == "Fixed Installments (Rate)":
                r_installments = st.number_input("Number of Installments", min_value=1, value=3, step=1)
                st.caption(f"Will stop after {r_installments} occurrences.")
            elif r_duration_type == "Until Date (Ends on)":
                r_end_date = st.date_input("End Date (Inclusive)")
                st.caption("Will stop generating after this date.")

            st.markdown("#### Details")
            r_desc = st.text_input("Description for Transaction", placeholder="e.g. Monthly subscription payment")
            
            # Tags handling
            existing_tags = data_manager.get_unique_tags()
            r_tags_sel = st.multiselect("Tags", existing_tags, placeholder="Select tags...")
            r_new_tag = st.text_input("Add New Tag (Optional)", placeholder="e.g. #subscription")
            
            submitted = st.form_submit_button("Save Template")
            
            if submitted:
                if not r_name:
                    st.error("Name is required.")
                else:
                    # Merge tags
                    final_tags = r_tags_sel
                    if r_new_tag:
                        clean = r_new_tag.strip().replace('#', '').lower()
                        if clean and clean not in final_tags:
                            final_tags.append(clean)
                    
                    # Final Description fallback
                    final_desc = r_desc if r_desc else r_name
                    
                    # Final Description fallback
                    final_desc = r_desc if r_desc else r_name
                    
                    data_manager.add_recurring(r_name, r_amount, r_cat, r_acc, r_freq, r_date, final_desc, final_tags, r_installments, r_end_date)
                    st.success(f"Recurring expense '{r_name}' added!")
                    st.rerun()

    st.divider()

    # --- List Existing ---
    st.subheader("📋 Active Templates")
    
    rec_df = data_manager.get_recurring()
    
    if not rec_df.empty:
        # Display as a table with more details
        # We can format it nicely
        
        # Show table
        st.dataframe(
            rec_df[['name', 'amount', 'frequency', 'next_date', 'remaining_installments', 'end_date', 'category', 'account']],
            use_container_width=True,
            hide_index=True,
            column_config={
                "amount": st.column_config.NumberColumn("Amount", format="€%.2f"),
                "next_date": st.column_config.DateColumn("Next Due"),
                "end_date": st.column_config.DateColumn("Ends On"),
                "remaining_installments": st.column_config.NumberColumn("Installments Left", help="Remaining payments"),
            }
        )
        
        # Delete Action
        col_del_1, col_del_2 = st.columns([3, 1])
        with col_del_1:
            rec_to_del = st.selectbox("Select Template to Remove", rec_df['name'], key='rec_del_swl')
        with col_del_2:
            st.write("") # Spacer
            st.write("")
            if st.button("🗑️ Delete", type="secondary", use_container_width=True):
                rec_id = rec_df[rec_df['name'] == rec_to_del].iloc[0]['id']
                data_manager.delete_recurring(rec_id)
                st.success("Deleted!")
                st.rerun()
                
    else:
        st.info("No recurring expenses set up yet.")
