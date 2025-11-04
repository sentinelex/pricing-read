# Quick Start Guide - UPRL Prototype

Get the Unified Pricing Read Layer prototype running in 5 minutes.

## Prerequisites

- Python 3.9 or higher
- Terminal/Command line access

## Installation & Launch

### Option 1: Quick Start Script (Recommended)

```bash
# Make script executable (first time only)
chmod +x run.sh

# Run the prototype
./run.sh
```

The script will:
1. Create a virtual environment (if needed)
2. Install dependencies
3. Launch the Streamlit app

### Option 2: Manual Setup

```bash
# 1. Create virtual environment
python3 -m venv venv

# 2. Activate virtual environment
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
streamlit run app.py
```

## First Steps

Once the app opens in your browser (`http://localhost:8501`):

### 1. Emit Your First Event

1. Navigate to **🎮 Producer Playground**
2. Select "Hotel 3-Night Booking (Simple)"
3. Click **📤 Emit Event**
4. You should see: ✅ "Ingested 3 components"

### 2. Explore the Order

1. Navigate to **🔍 Order Explorer**
2. Select the order ID from the dropdown (e.g., `ORD-9001`)
3. View the **💰 Latest Breakdown** tab
4. See the three components:
   - BaseFare (IDR 1,500.00)
   - Tax (IDR 165.00)
   - Fee (IDR 50.00)

### 3. Add a Refund

1. Go back to **🎮 Producer Playground**
2. Click the **↩️ Refund Events** tab
3. Select **Component Events (Refund Issued)**
4. Update the `order_id` to match your hotel booking
5. Update the `refund_of_component_semantic_id` to match the BaseFare semantic ID
   - Copy from Order Explorer: something like `cs-ORD-9001-OD-OD-001-BaseFare`
6. Click **📤 Emit Event**

### 4. View Component Lineage

1. Navigate to **🔍 Order Explorer** → **🔗 Component Lineage**
2. Select the BaseFare component
3. See:
   - **Original Component**: The initial BaseFare
   - **Refund Components**: The refund with lineage pointer

## Test Scenarios

### Scenario 1: Out-of-Order Events

Navigate to **🧪 Stress Tests** → "Out-of-Order Events"

1. Enter a unique Order ID (e.g., `ORD-OOO-TEST1`)
2. Click **Emit Version 3 First**
3. Click **Emit Version 2 Second**
4. Go to Order Explorer → Version History
5. Result: Both versions stored correctly, latest view shows v3

### Scenario 2: Invalid Event (DLQ)

Navigate to **🧪 Stress Tests** → "Invalid Event Schema"

1. Click **Emit Invalid Event**
2. See: ❌ "Event sent to DLQ"
3. Navigate to **⚙️ Ingestion Console**
4. Expand the DLQ entry to see error details

### Scenario 3: Payment Timeline

1. Emit a pricing event (any scenario)
2. Go to **🎮 Producer Playground** → **💳 Payment Events**
3. Select "payment.checkout" → Emit
4. Select "payment.captured" → Emit
5. Go to **🔍 Order Explorer** → **💳 Payment Timeline**
6. See the complete payment lifecycle

## Validation Test

Run the automated test suite:

```bash
source venv/bin/activate
python3 test_prototype.py
```

Expected output: ✅ ALL TESTS PASSED!

## Common Issues

### "ModuleNotFoundError: No module named 'streamlit'"
- Make sure virtual environment is activated: `source venv/bin/activate`
- Reinstall dependencies: `pip install -r requirements.txt`

### "No orders found"
- Emit at least one pricing event via Producer Playground

### Database errors
- Clear data via **⚙️ Settings** → "Clear All Data"
- Or delete `data/uprl.db` and restart

### Port already in use
- Stop other Streamlit apps or specify different port:
  ```bash
  streamlit run app.py --server.port 8502
  ```

## Key Features to Explore

- **Dual ID System**: Check semantic IDs in Order Explorer (stable across versions)
- **Version History**: See how pricing evolves over time
- **Component Lineage**: Trace refunds back to original components
- **DLQ**: Send invalid events to see validation in action
- **Multi-Track Events**: Pricing, Payment, Supplier, Refund all independent

## Next Steps

After exploring the prototype:

1. Read [README.md](README.md) for detailed architecture
2. Review [prototype.md](prototype.md) for implementation details
3. Check `src/` code to understand the pipeline logic
4. Consult [../prd_v2.md](../prd_v2.md) for product requirements

## Need Help?

- Check the **🏠 Home** page for architecture overview
- Review the README.md for troubleshooting
- Inspect the code in `src/` directories

---

**Happy exploring!** 🚀
