import streamlit as st
import pandas as pd
from src.data_manager import DataManager


def render_transactions(data_manager: DataManager):
    st.header("Transactions")

    try:
        df = data_manager.con.execute("SELECT * FROM transactions ORDER BY date DESC").df()

        if df.empty:
            st.info("No data available.")
            return

        df['date'] = pd.to_datetime(df['date'])

        # ── Filters ────────────────────────────────────────────────────────────
        col1, col2, col3 = st.columns(3)
        # Pre-fill from global search if set
        default_search = st.session_state.get('global_search', '')
        search = col1.text_input("Search Description", value=default_search)
        category_filter = col2.multiselect("Filter Category", options=sorted(df['category'].dropna().unique()))

        all_tags = set()
        for tags_list in df['tags']:
            if isinstance(tags_list, list):
                all_tags.update(tags_list)
            elif hasattr(tags_list, 'tolist'):
                all_tags.update(tags_list.tolist())
        tag_filter = col3.multiselect("Filter Tags", options=sorted(list(all_tags)))

        col4, col5, col6 = st.columns(3)
        type_filter = col4.selectbox("Type", ["All", "Expense", "Income", "Transfer"])
        min_date = df['date'].dt.date.min()
        max_date = df['date'].dt.date.max()
        date_range = col5.date_input("Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
        all_amounts = df['amount'].abs()
        amount_range = col6.slider(
            "Amount (€)",
            min_value=0.0,
            max_value=float(all_amounts.max()) if not all_amounts.empty else 10000.0,
            value=(0.0, float(all_amounts.max()) if not all_amounts.empty else 10000.0),
            step=1.0
        )

        # Apply filters
        filtered_df = df.copy()
        if search:
            filtered_df = filtered_df[filtered_df['description'].str.contains(search, case=False, na=False)]
        if category_filter:
            filtered_df = filtered_df[filtered_df['category'].isin(category_filter)]
        if tag_filter:
            def has_tag(row_tags):
                if not row_tags:
                    return False
                rt = row_tags.tolist() if hasattr(row_tags, 'tolist') else row_tags
                return bool(set(rt) & set(tag_filter)) if isinstance(rt, list) else False
            filtered_df = filtered_df[filtered_df['tags'].apply(has_tag)]
        if type_filter != "All":
            filtered_df = filtered_df[filtered_df['type'] == type_filter]
        if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
            start_d, end_d = date_range
            filtered_df = filtered_df[
                (filtered_df['date'].dt.date >= start_d) &
                (filtered_df['date'].dt.date <= end_d)
            ]
        filtered_df = filtered_df[
            (filtered_df['amount'].abs() >= amount_range[0]) &
            (filtered_df['amount'].abs() <= amount_range[1])
        ]

        st.caption(f"Showing {len(filtered_df):,} of {len(df):,} transactions")

        # ── Export ─────────────────────────────────────────────────────────────
        csv_bytes = filtered_df.drop(columns=['id'], errors='ignore').to_csv(index=False).encode('utf-8')
        st.download_button(
            label="⬇️ Export filtered CSV",
            data=csv_bytes,
            file_name="transactions_export.csv",
            mime="text/csv"
        )

        st.divider()

        # ── Tabs: Edit | Bulk Actions ───────────────────────────────────────────
        tab_edit, tab_bulk = st.tabs(["✏️ Edit Transactions", "⚡ Bulk Actions"])

        # ── Tab 1: Edit ────────────────────────────────────────────────────────
        with tab_edit:
            st.info("💡 Double-click a cell to edit. Press **Save Changes** to persist.")

            column_config = {
                "id": None,
                "original_description": None,
                "source_file": None,
                "date": st.column_config.DateColumn("Date"),
                "amount": st.column_config.NumberColumn("Amount", format="€%.2f"),
                "type": st.column_config.SelectboxColumn("Type", options=["Expense", "Income", "Transfer"]),
                "category": st.column_config.SelectboxColumn("Category", options=data_manager.get_unique_categories() + ["Other"]),
                "necessity": st.column_config.SelectboxColumn("Necessity", options=["Need", "Want"]),
                "tags": st.column_config.ListColumn("Tags"),
                "notes": st.column_config.TextColumn("Notes", help="Personal note for this transaction"),
            }

            edited_df = st.data_editor(
                filtered_df,
                column_config=column_config,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="data_editor"
            )

            if st.button("Save Changes", key="save_edit"):
                original_ids = set(filtered_df['id'].dropna())
                current_ids = set(edited_df['id'].dropna())
                deleted_ids = original_ids - current_ids

                if deleted_ids:
                    ids_list = list(deleted_ids)
                    placeholders = ','.join(['?'] * len(ids_list))
                    data_manager.con.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", ids_list)
                    st.toast(f"Deleted {len(deleted_ids)} rows")

                new_rows = edited_df[edited_df['id'].isna() | (edited_df['id'] == '')]
                if not new_rows.empty:
                    for _, row in new_rows.iterrows():
                        r_amt = row['amount']
                        if row['type'] == 'Expense' and r_amt > 0:
                            r_amt = -r_amt
                        if row['type'] == 'Income' and r_amt < 0:
                            r_amt = -r_amt
                        notes_val = row.get('notes', None)
                        q = "INSERT INTO transactions (id, date, amount, currency, account, category, description, type, necessity, notes) VALUES (uuid(), ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                        data_manager.con.execute(q, [row['date'], r_amt, row.get('currency', 'EUR'), row['account'], row['category'], row['description'], row['type'], row.get('necessity', 'Want'), notes_val])
                    st.toast(f"Added {len(new_rows)} new rows")

                changes_count = 0
                merged = filtered_df.merge(edited_df, on='id', suffixes=('_old', '_new'))
                cols_to_check = ['date', 'amount', 'type', 'category', 'description', 'necessity', 'tags', 'notes']
                mask = pd.Series([False] * len(merged))

                for col in cols_to_check:
                    if f'{col}_old' not in merged.columns or f'{col}_new' not in merged.columns:
                        continue
                    c_old = merged[f'{col}_old'].fillna('')
                    c_new = merged[f'{col}_new'].fillna('')
                    if col == 'tags':
                        def normalize_for_cmp(x):
                            if isinstance(x, list): return tuple(sorted(x))
                            if isinstance(x, str) and x == '': return ()
                            if hasattr(x, 'tolist'): return tuple(sorted(x.tolist()))
                            return x if x else ()
                        mask |= (c_old.apply(normalize_for_cmp) != c_new.apply(normalize_for_cmp))
                    else:
                        mask |= (c_old != c_new)

                for _, row in merged[mask].iterrows():
                    r_amt = row['amount_new']
                    if row['type_new'] == 'Expense' and r_amt > 0:
                        r_amt = -r_amt
                    if row['type_new'] == 'Income' and r_amt < 0:
                        r_amt = -r_amt
                    notes_val = row.get('notes_new', None)
                    q = """
                        UPDATE transactions
                        SET date=?, amount=?, type=?, category=?, description=?, necessity=?, tags=?, notes=?
                        WHERE id=?
                    """
                    data_manager.con.execute(q, [row['date_new'], r_amt, row['type_new'], row['category_new'], row['description_new'], row['necessity_new'], row['tags_new'], notes_val, row['id']])
                    changes_count += 1

                if changes_count > 0:
                    st.toast(f"Updated {changes_count} rows")

                if changes_count > 0 or not new_rows.empty or deleted_ids:
                    st.success("Saved successfully!")
                    st.rerun()
                else:
                    st.info("No changes detected.")

        # ── Tab 2: Bulk Actions ────────────────────────────────────────────────
        with tab_bulk:
            st.info("Select rows, then choose an action to apply to all selected transactions.")

            display_cols = ['date', 'description', 'category', 'amount', 'account', 'tags']
            bulk_event = st.dataframe(
                filtered_df[display_cols + ['id']],
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="multi-row",
                key="bulk_selector",
                column_config={"id": None}
            )

            selected_indices = bulk_event.selection.rows if bulk_event and bulk_event.selection else []

            if selected_indices:
                selected_ids = filtered_df.iloc[selected_indices]['id'].tolist()
                st.success(f"{len(selected_ids)} rows selected")

                cats = data_manager.get_unique_categories()
                all_tags_list = data_manager.get_unique_tags()

                with st.form("bulk_action_form"):
                    st.markdown("**Apply to selected rows:**")
                    bc1, bc2, bc3 = st.columns(3)
                    bulk_cat = bc1.selectbox("Set Category", ["(keep)"] + cats)
                    bulk_necessity = bc2.selectbox("Set Necessity", ["(keep)", "Need", "Want"])
                    bulk_tag = bc3.text_input("Add Tag", placeholder="e.g. vacanze")

                    bd1, bd2 = st.columns([1, 3])
                    do_delete = bd1.checkbox("Delete selected rows", value=False)

                    submitted = st.form_submit_button("Apply", type="primary")
                    if submitted:
                        if do_delete:
                            placeholders = ','.join(['?'] * len(selected_ids))
                            data_manager.con.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", selected_ids)
                            st.success(f"Deleted {len(selected_ids)} rows")
                            st.rerun()
                        else:
                            updated = 0
                            if bulk_cat != "(keep)":
                                placeholders = ','.join(['?'] * len(selected_ids))
                                data_manager.con.execute(
                                    f"UPDATE transactions SET category = ? WHERE id IN ({placeholders})",
                                    [bulk_cat] + selected_ids
                                )
                                updated += 1
                            if bulk_necessity != "(keep)":
                                placeholders = ','.join(['?'] * len(selected_ids))
                                data_manager.con.execute(
                                    f"UPDATE transactions SET necessity = ? WHERE id IN ({placeholders})",
                                    [bulk_necessity] + selected_ids
                                )
                                updated += 1
                            if bulk_tag.strip():
                                clean_tag = bulk_tag.strip().replace('#', '').lower()
                                placeholders = ','.join(['?'] * len(selected_ids))
                                data_manager.con.execute(
                                    f"UPDATE transactions SET tags = list_distinct(list_append(tags, ?)) WHERE id IN ({placeholders})",
                                    [clean_tag] + selected_ids
                                )
                                updated += 1
                            if updated > 0:
                                st.success(f"Updated {len(selected_ids)} rows")
                                st.rerun()
                            else:
                                st.info("No action selected.")
            else:
                st.caption("No rows selected. Click rows in the table above to select them.")

    except Exception as e:
        st.error(f"Error loading transactions: {e}")
        import traceback
        st.text(traceback.format_exc())
