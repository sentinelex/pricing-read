# Refund Instruction (Component-Level) — Unified Pricing Read Layer

**Owner:** Order Core PM  
**Applies to:** Pricing/Refund producers, Order Core ingestion, CS/Finance/BI consumers  
**Last Updated:** 2025‑11‑03

---

## 1) Purpose

Guarantee that **refund components** are modeled, stored, and queried in a way that:
- Uses the **same semantic component identity and granularity** as the original commercial charge.
- Remains **append‑only** (no overwrites), enabling perfect lineage.
- Allows a **single, deterministic query** to compute **latest** and **net** amounts per component.
- Makes **`is_refund` a per‑component truth**, not just an event hint.

---

## 2) Canonical identity & granularity (non‑negotiable)

### 2.1 Component identity

Order Core mints two IDs for every stored component row:
- **`component_semantic_id`**: Stable logical identity for the commercial intent  
  Construction =  
  ```
  cs-{order_id}-{canonical_dimensions_in_order}-{component_type}-{optional_key}
  ```
  - **Dimensions** must be **canonicalized** (sorted keys; normalized values).
  - **`optional_key`** (from `meta`) is only used when product logic requires multiple parallel semantics of the *same* type at the same granularity (e.g., joint subsidy by different funders).

- **`component_instance_id`**: Unique identity of the **occurrence** of that semantic component in a given snapshot  
  Construction (deterministic) =  
  ```
  ci = H(cs || pricing_snapshot_id)
  ```

> Refund rows **reuse the same `component_semantic_id`** as the original they reverse. This preserves “latest by semantic” logic and makes lineage trivial.

### 2.2 Granularity (dimensions)

Refund rows **must match the original component’s granularity**:
- Flights example: `{order_detail_id, pax_id, leg_id}`
- Accommodation example: `{order_detail_id, stay_night}`
- Car rental example: `{order_detail_id, rental_day}`

**Rule:** a refund component’s `dimensions` must be **identical in shape and values** to the original’s `dimensions`. If the producer can’t supply the same shape, the event is rejected to DLQ with a **granularity_mismatch** error.

---

## 3) Data contract for refund components

### 3.1 Producer → Order Core (event contract)

For each refund item:
```json
{
  "component_type": "RoomRate",
  "amount": -1000000,
  "currency": "IDR",
  "dimensions": { "order_detail_id": "OD-1", "stay_night": "2025-11-10" },
  "description": "Partial refund - 1 night",
  "refund_of_component_semantic_id": "cs-ORD-1-OD-1-2025-11-10-RoomRate",
  "meta": { "reason": "guest_cancelled" }
}
```

**Rules**
- Refund **reverses the economic impact** of the original row. If the original increased the customer total (e.g., BaseFare, Tax, Markup), the refund amount must be **negative**. If the original decreased the customer total (e.g., Discount, Promo, Subsidy), the refund amount must be **positive**.
- Order Core derives this from taxonomy (component_type → economic_direction ∈ {charge, credit}). Refund must flip the direction of the original.
- `refund_of_component_semantic_id` **must** point to an **existing** semantic id in prior snapshots of the same `order_id`.
- If the original used an **`optional_key`** (e.g., `funding_source=platform`), the refund must **include the same key/value** in `meta` so Order Core can produce an identical `component_semantic_id`.

### 3.2 Order Core → Storage (normalized)

Order Core writes each row to `pricing_components_fact` with:
- `component_semantic_id` (stable)
- `component_instance_id` (deterministic per snapshot)
- `order_id, pricing_snapshot_id, version`
- `component_type, amount, currency`
- `dimensions` (JSON), **canonicalized**
- `is_refund` **(BOOLEAN, REQUIRED)**
- `refund_of_component_semantic_id` (nullable; filled if `is_refund=true`)
- `emitter_service, emitted_at, ingested_at`
- `metadata` (JSON; optional)

### 3.3 Economic direction & sign conventions

Each `component_type` has a **canonical economic direction** (from the customer-total perspective):

| Component type (examples) | Canonical direction | Example original | Example refund |
|---|---|---:|---:|
| BaseFare, RoomRate, Ancillary, Markup, ServiceFee | charge (+) | +1,000,000 | −1,000,000 |
| Discount, Promo, LoyaltyRedeem, Subsidy | credit (−) | −100,000 | +100,000 |
| RefundPenalty, NoShowPenalty | charge (+) | +80,000 | −80,000 |

**Rule:** `sign(refund.amount) = − sign(original.amount)`.

Order Core validates by checking that `refund.amount * original.amount < 0` (after currency normalization if applicable).

---

## 4) Validation rules (ingestion governance)

Order Core validates each refund component:

1. **Currency/Amount**
   - Refund amount must **invert** the original's sign: if the original was positive (charge), refund is negative; if original was negative (credit), refund is positive.
   - Currency equals the original’s currency (or convertible per policy).
2. **Granularity shape**
   - The `dimensions` **keys and values** must match the original **exactly** (same keys; same normalized values).
3. **Lineage**
   - `refund_of_component_semantic_id` exists for the same `order_id`.
4. **Identity**
   - Canonical `component_semantic_id` minted from **(order_id + dimensions + component_type + optional_key)** must equal `refund_of_component_semantic_id`.  
     If not, **reject** with `semantic_mismatch`.
5. **Immutability**
   - Append‑only write. No updates to previous rows.

Failures → **DLQ** with explicit `error_type`:
- `granularity_mismatch`
- `semantic_mismatch`
- `missing_original_component`
- `invalid_amount_sign`
- `currency_mismatch`

---

## 5) Query cookbook (latest & net)

> Works with SQLite/BigQuery; adjust type functions as needed.

### 5.1 Latest‑by‑semantic (ignoring refund sign)

Returns **the last occurrence** per semantic (could be a refund or a price row — use `is_refund` to interpret).

```sql
WITH ranked AS (
  SELECT
    order_id,
    component_semantic_id,
    component_type,
    amount,
    currency,
    is_refund,
    version,
    emitted_at,
    ROW_NUMBER() OVER (
      PARTITION BY order_id, component_semantic_id
      ORDER BY version DESC, emitted_at DESC
    ) AS rn
  FROM pricing_components_fact
  WHERE order_id = @order_id
)
SELECT *
FROM ranked
WHERE rn = 1;
```

### 5.2 Net amount per semantic (price minus refunds)

Compute **net** by summing **all** rows per semantic (originals positive, refunds negative):

```sql
SELECT
  order_id,
  component_semantic_id,
  component_type,
  currency,
  SUM(amount) AS net_amount
FROM pricing_components_fact
WHERE order_id = @order_id
GROUP BY order_id, component_semantic_id, component_type, currency;
```

### 5.3 Net by “latest base” + “all refunds” (if you must keep “latest price only” semantics)

If your product UI wants “latest price magnitude” minus “all historical refunds”:

```sql
WITH latest_price AS (
  SELECT order_id, component_semantic_id, amount AS latest_amount
  FROM (
    SELECT
      order_id,
      component_semantic_id,
      amount,
      is_refund,
      ROW_NUMBER() OVER (
        PARTITION BY order_id, component_semantic_id
        ORDER BY version DESC, emitted_at DESC
      ) AS rn
    FROM pricing_components_fact
    WHERE is_refund = 0
  )
  WHERE rn = 1
),
refund_sum AS (
  SELECT
    order_id,
    refund_of_component_semantic_id AS component_semantic_id,
    SUM(amount) AS refunds_sum
  FROM pricing_components_fact
  WHERE is_refund = 1
  GROUP BY 1,2
)
SELECT
  lp.order_id,
  lp.component_semantic_id,
  lp.latest_amount,
  COALESCE(rs.refunds_sum, 0) AS refunds_sum,
  lp.latest_amount + COALESCE(rs.refunds_sum, 0) AS net_amount
FROM latest_price lp
LEFT JOIN refund_sum rs
  ON rs.order_id = lp.order_id
 AND rs.component_semantic_id = lp.component_semantic_id;
```

> **Note:** This pattern relies on the fact that refunds carry `refund_of_component_semantic_id` equal to the base’s **semantic id**, and that `is_refund` is **per‑row**.

---

## 6) Examples

### 6.1 Accommodation (per‑night granularity)

**v1 (original):**
```json
{
  "component_type": "RoomRate",
  "amount": 1000000,
  "currency": "IDR",
  "dimensions": { "order_detail_id": "OD-1", "stay_night": "2025-11-10" },
  "meta": null
}
```

**v3 (refund one night):**
```json
{
  "component_type": "RoomRate",
  "amount": -1000000,
  "currency": "IDR",
  "dimensions": { "order_detail_id": "OD-1", "stay_night": "2025-11-10" },
  "refund_of_component_semantic_id": "cs-ORD-1-OD-1-2025-11-10-RoomRate",
  "meta": { "reason": "guest_cancelled" }
}
```

**Stored rows (abbrev):**
| version | component_semantic_id                               | amount   | is_refund |
|--------:|------------------------------------------------------|---------:|:---------:|
| 1       | cs-ORD-1-OD-1-2025-11-10-RoomRate                    | 1,000,000|    0      |
| 3       | cs-ORD-1-OD-1-2025-11-10-RoomRate                    | -1,000,000|   1      |

**Net query (5.2)** ⇒ `0`.

### 6.1b Subsidy refund (credit reversed)

**v1 (original subsidy):**
```json
{
  "component_type": "Subsidy",
  "amount": -100000,
  "currency": "IDR",
  "dimensions": { "order_detail_id": "OD-1" },
  "meta": { "funding_source": "platform" }
}
```

**v3 (refund of subsidy):**
```json
{
  "component_type": "Subsidy",
  "amount": 100000,
  "currency": "IDR",
  "dimensions": { "order_detail_id": "OD-1" },
  "refund_of_component_semantic_id": "cs-ORD-1-OD-1-Subsidy-fs:platform",
  "meta": { "funding_source": "platform", "reason": "refund_full" }
}
```

**Stored rows (abbrev):**
| version | component_semantic_id                         | amount   | is_refund |
|--------:|----------------------------------------------|---------:|:---------:|
| 1       | cs-ORD-1-OD-1-Subsidy-fs:platform             | -100,000 |    0      |
| 3       | cs-ORD-1-OD-1-Subsidy-fs:platform             |  100,000 |    1      |

**Net query (5.2)** ⇒ `0`.

### 6.2 Joint subsidy (two funders, same granularity)

**v1 (original):**
- `Subsidy` (platform) `-50,000` → `meta.funding_source="platform"`
- `Subsidy` (supplier) `-25,000` → `meta.funding_source="supplier"`

Order Core canonicals:
```
cs-ORD-1-OD-1-...-Subsidy-fs:platform
cs-ORD-1-OD-1-...-Subsidy-fs:supplier
```

**v3 (refund platform part only):**
- Refund row carries **same optional_key** (`fs:platform`), negative amount, and `refund_of_component_semantic_id` pointing to `...Subsidy-fs:platform`.

---

## 7) Pitfalls & how to avoid them

1. **Event‑level refund flag**  
   Do **not** infer refund solely from the event type. Always use per‑row `is_refund`.

2. **Dimension mismatch**  
   If the original is per‑night and refund is per‑order_detail only, **reject**. Ask producer to send the correct granularity.

3. **Missing optional key in refund**  
   If original used `optional_key` (e.g., `funding_source`), the refund must include the same key/value; otherwise you’ll create a different semantic id.

4. **Currency drift**  
   Refund currency must match the base’s currency (or explicit conversion policy). Otherwise, DLQ with `currency_mismatch`.

5. **Zero‑decimal currency scaling**  
   Store IDR/JPY as **main units** (no `*100`). Avoid double-scaling.

---

## 8) Test checklist (must pass)

- [ ] Refund row ingested with `is_refund = 1`, `amount < 0`.
- [ ] `refund_of_component_semantic_id` exists for the same order.
- [ ] Canonicalized dimensions of refund equal the original’s.
- [ ] `component_semantic_id` of refund **equals** `refund_of_component_semantic_id`.
- [ ] Latest‑by‑semantic (5.1) returns **the last occurrence** (refund or price).
- [ ] Net (5.2) equals “sum of all occurrences” for the semantic id.
- [ ] UI “Latest + refunds” computed via (5.3) where needed.
- [ ] DLQ fires for each validation failure type with actionable messages.

---

## 9) FAQ

**Q:** Should we suffix the semantic id with `_refund`?  
**A:** **No.** Refund rows use the **same semantic id**; the refundness is captured by `is_refund=1` and the negative amount.

**Q:** Can a single event mix refund and non‑refund components?  
**A:** Yes. That’s why `is_refund` is per‑row.

**Q:** What about BNPL?  
**A:** Refund modeling is independent of payment timelines. Payment state lives in **PaymentTimeline**; components remain immutable facts.

**Q:** Are refund amounts always negative?  
**A:** No. Refunds must **reverse the sign** of the original. For **charges** (e.g., BaseFare) refunds are negative; for **credits** (e.g., Subsidy, Discount) refunds are positive.

---

## 10) Appendix — reference table definitions (excerpt)

Add these columns (or verify existence) in `pricing_components_fact`:

```sql
-- Required columns (excerpt)
component_semantic_id TEXT,
component_instance_id TEXT,
order_id TEXT,
pricing_snapshot_id TEXT,
version INT,
component_type TEXT,
amount INT,
currency TEXT,
dimensions JSON,
is_refund BOOLEAN,  -- NEW: per-row flag
refund_of_component_semantic_id TEXT,  -- nullable
emitter_service TEXT,
emitted_at TIMESTAMP,
ingested_at TIMESTAMP,
metadata JSON
```

> If your local prototype uses SQLite, treat `BOOLEAN` as `INTEGER` (0/1). In BigQuery, use `BOOL`.

---

**End of document**