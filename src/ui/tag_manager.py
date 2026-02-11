import streamlit as st
import pandas as pd
from src.data_manager import DataManager

def render_tag_manager(data_manager: DataManager):
    st.header("🏷️ Tag Manager")
    
    st.info("Manage your tags here. You can rename tags or merge them (by renaming one to an existing name).")
    
    # Get all tags and stats
    try:
        # We need counts.
        # Efficient way: Get all tags unnested and count
        df = data_manager.con.execute("SELECT unnest(tags) as tag FROM transactions").df()
        if df.empty:
            st.warning("No tags found.")
            return
            
        tag_counts = df['tag'].value_counts().reset_index()
        tag_counts.columns = ['Tag', 'Count']
        tag_counts = tag_counts.sort_values('Count', ascending=False)
        
        all_tags = sorted(tag_counts['Tag'].unique().tolist())
        
    except Exception as e:
        st.error(f"Error loading tags: {e}")
        return

    # --- Actions ---
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Rename / Merge")
        
        target_tag = st.selectbox("Select Tag to Edit", all_tags, key="tag_to_edit")
        
        # Suggest current name as default, but selectbox returns value
        new_name = st.text_input("New Name", value=target_tag)
        
        if st.button("Update Tag", type="primary"):
            if new_name and new_name != target_tag:
                clean_new = new_name.strip().lower().replace('#', '')
                
                # Check if merging
                is_merge = clean_new in all_tags
                msg = f"Renaming '{target_tag}' to '{clean_new}'"
                if is_merge:
                    msg += f" (Merging with existing '{clean_new}')"
                
                with st.spinner("Updating..."):
                    success, res = data_manager.update_tag(target_tag, clean_new)
                    if success:
                        st.success(f"Success! {res}")
                        st.rerun()
                    else:
                        st.error(f"Error: {res}")
            elif not new_name:
                st.error("Name cannot be empty.")
            else:
                st.info("No changes made.")

    with col2:
        st.subheader("Cleanup")
        st.write("Delete a tag completely from all transactions.")
        
        del_tag = st.selectbox("Select Tag to Delete", all_tags, key="tag_to_del")
        
        if st.button("🗑️ Delete Tag", type="secondary"):
            with st.spinner("Deleting..."):
                success, res = data_manager.update_tag(del_tag, None) # None means delete logic in DM
                if success:
                    st.success(f"Deleted tag '{del_tag}'")
                    st.rerun()
                else:
                    st.error(f"Error: {res}")

    st.divider()
    
    # Properties Table
    st.subheader(f"All Tags ({len(all_tags)})")
    st.dataframe(tag_counts, use_container_width=True, hide_index=True)
