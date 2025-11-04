#!/bin/bash

# UPRL Prototype - Quick Start Script

echo "🚀 Starting Unified Pricing Read Layer Prototype..."
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -q -r requirements.txt

# Create data directory if it doesn't exist
mkdir -p data

# Run Streamlit app
echo ""
echo "✅ Setup complete!"
echo "🌐 Starting Streamlit app..."
echo ""

streamlit run app.py
