import streamlit as st

def apply_custom_styles():
    st.markdown("""
        <style>
        /* Metrics styling */
        [data-testid="stMetricValue"] {
            font-size: 2rem;
            font-weight: bold;
            color: #4CAF50; /* Green for positive vibes */
        }
        
        /* Make dividers less obtrusive */
        hr {
            margin-top: 1rem;
            margin-bottom: 1rem;
            border-color: #eee;
        }
        
        /* Card-like effect for containers (optional, Streamlit containers are flat by default) */
        .stMarkdown {
            /* font-family: 'Inter', sans-serif; */
        }
        
        /* Adjust padding for cleaner look */
        .block-container {
            padding-top: 2rem;
        }
        </style>
    """, unsafe_allow_html=True)

def get_chart_colors():
    # A professional, soft palette
    return ["#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A", "#19D3F3", "#FF6692", "#B6E880"]
