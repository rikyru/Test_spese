import streamlit as st
import pandas as pd
from src.data_manager import DataManager

def render_tag_manager(data_manager: DataManager):
    st.header("🏷️ Gestione tag")
    
    st.info("Rinomina i tag o uniscili (rinominandone uno con il nome di un tag esistente).")
    
    # Get all tags and stats
    try:
        # We need counts.
        # Efficient way: Get all tags unnested and count
        df = data_manager.con.execute("SELECT unnest(tags) as tag FROM transactions").df()
        if df.empty:
            st.warning("Nessun tag trovato.")
            return
            
        tag_counts = df['tag'].value_counts().reset_index()
        tag_counts.columns = ['Tag', 'Count']
        tag_counts = tag_counts.sort_values('Count', ascending=False)
        
        all_tags = sorted(tag_counts['Tag'].unique().tolist())
        
    except Exception as e:
        st.error(f"Errore nel caricamento dei tag: {e}")
        return

    # --- Actions ---
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Rinomina / unisci")
        
        target_tag = st.selectbox("Tag da modificare", all_tags, key="tag_to_edit")
        
        # Suggest current name as default, but selectbox returns value
        new_name = st.text_input("Nuovo nome", value=target_tag)
        
        if st.button("Aggiorna tag", type="primary"):
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
                        st.success(f"Fatto! {res}")
                        st.rerun()
                    else:
                        st.error(f"Errore: {res}")
            elif not new_name:
                st.error("Il nome non può essere vuoto.")
            else:
                st.info("Nessuna modifica.")

    with col2:
        st.subheader("Pulizia")
        st.write("Elimina un tag da tutti i movimenti.")
        
        del_tag = st.selectbox("Tag da eliminare", all_tags, key="tag_to_del")
        
        if st.button("🗑️ Elimina tag", type="secondary"):
            with st.spinner("Deleting..."):
                success, res = data_manager.update_tag(del_tag, None) # None means delete logic in DM
                if success:
                    st.success(f"Tag '{del_tag}' eliminato")
                    st.rerun()
                else:
                    st.error(f"Errore: {res}")

    st.divider()
    
    # Properties Table
    st.subheader(f"Tutti i tag ({len(all_tags)})")
    st.dataframe(tag_counts, use_container_width=True, hide_index=True)
