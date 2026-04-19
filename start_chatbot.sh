#!/bin/bash
cd /Users/kazuhiro/Desktop/shopee-research
source venv/bin/activate
streamlit run shopee_chatbot.py --server.port 8501 --server.headless false
