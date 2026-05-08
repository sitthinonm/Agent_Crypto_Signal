# Bias Calculation Reference (from `JB_SMCRP Pro2.pine`)

เอกสารนี้สรุป logic การคำนวณ Bias จากสคริปต์ Pine เพื่อใช้ต่อใน Agent Crypto Futures Analyzer

## 1) HTF Bias (Directional Context)

ใช้ MTF EMA cross ที่ 30m / 1h / 4h / 1D พร้อมน้ำหนัก

- `mtfWeight30 = 1`
- `mtfWeight1H = 2`
- `mtfWeight4H = 3`
- `mtfWeight1D = 4`

### Long score (MTF)
เพิ่มคะแนนเมื่อ:

- `fastEMA > slowEMA`
- หรือ `fastEMA == slowEMA` และ `close > slowEMA`

### Short score (MTF)
เพิ่มคะแนนเมื่อ:

- `fastEMA < slowEMA`
- หรือ `fastEMA == slowEMA` และ `close < slowEMA`

### Bias output

- `htfLongBias = (mtfLongScore > mtfShortScore)`
- `htfShortBias = (mtfShortScore > mtfLongScore)`
- `htfNeutral = not htfLongBias and not htfShortBias`

---

## 2) LTF Score Bias (Execution Context)

คำนวณ `longScore` และ `shortScore` จาก confluence รายแท่ง

### `longScore` components

- trend long: `+1`
- touch discount zone: `+2`
- in discount zone: `+1`
- EMA retest long: `+1`
- reversal long ready: `+1`
- continuation long ready: `+1`
- HTF support (`useHTFBias && htfLongBias`): `+1`
- volume OK: `+1`
- range OK: `+1`

### `shortScore` components

สมมาตรฝั่ง short:

- trend short: `+1`
- touch premium zone: `+2`
- in premium zone: `+1`
- EMA retest short: `+1`
- reversal short ready: `+1`
- continuation short ready: `+1`
- HTF support (`useHTFBias && htfShortBias`): `+1`
- volume OK: `+1`
- range OK: `+1`

---

## 3) Threshold / Gate Context (ที่เกี่ยวกับ Bias)

- `baseThreshold` ตาม profile + timeframe
- `longThreshold`, `shortThreshold` หลัง relax ตาม TF สูง
- `hitsLong`, `hitsShort` ใช้ยืนยันคุณภาพสัญญาณ
- `gapLongOK = longScore >= shortScore - 2`
- `gapShortOK = shortScore >= longScore - 2`

หมายเหตุ: ส่วนนี้คือ gate สำหรับ setup/signal ไม่ใช่ bias label เพียงอย่างเดียว

---

## 4) Final Resolve Rule (เมื่อชนกัน)

ถ้า long/short เกิดพร้อมกัน ใช้คะแนนตัดสิน:

- `longSignal` ชนะเมื่อ `longScore > shortScore`
- `shortSignal` ชนะเมื่อ `shortScore > longScore`

ถ้าเกิดข้างเดียวก็ใช้ข้างนั้นโดยตรง

---

## 5) Dashboard Bias Display

- ถ้า `useHTFBias = true`:
  - bias จาก `htfLongBias / htfShortBias / htfNeutral`
- ถ้าปิด `useHTFBias`:
  - bias จาก local trend (`trendLong` / `trendShort`)

---

## 6) Confidence Formula (ใช้ใน dashboard)

```text
confidence_pct =
  clamp(
    100 * (max(longScore, shortScore) - min(longScore, shortScore)) / max(1, max(longScore, shortScore)),
    0,
    99
  )
```

---

## 7) Mapping สำหรับ Agent Output

แนะนำให้ Agent ส่งฟิลด์เหล่านี้:

- `htf_bias`: `LONG | SHORT | NEUTRAL`
- `mtf_long_score`, `mtf_short_score`, `mtf_bias_delta`
- `ltf_long_score`, `ltf_short_score`, `ltf_bias_delta`
- `dominant_bias`: `LONG | SHORT | NEUTRAL`
- `confidence_pct`
- `bias_reasons`: เหตุผลหลัก 3-5 ข้อว่าทำไม bias ฝั่งนั้นชนะ

---

## 8) Implementation Note (for Agent service)

เพื่อให้ behavior ใกล้ Pine:

1. ใช้ timeframe เดียวกันตอนดึง MTF
2. ใช้ EMA period เดียวกันกับ Pine
3. แยก `HTF bias` และ `LTF execution score` เป็นคนละชั้น
4. อย่าให้ `confidence` ไป override bias ตรงๆ (ใช้เป็นระดับความมั่นใจ ไม่ใช่ตัวสลับทิศ)
