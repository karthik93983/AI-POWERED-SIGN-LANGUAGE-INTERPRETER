from flask import Flask, request, jsonify
from flask_cors import CORS
import json, re, math

app = Flask(__name__)
CORS(app)

# ── Landmark parser ───────────────────────────────────────────────────────────
def parse_landmarks(prompt):
    landmarks = {}
    matches = re.findall(r'(\d+):\(([\d.\-]+),([\d.\-]+),([\d.\-]+)\)', prompt)
    for m in matches:
        landmarks[int(m[0])] = {'x': float(m[1]), 'y': float(m[2]), 'z': float(m[3])}
    return landmarks

def dist(a, b):
    return math.sqrt((a['x']-b['x'])**2 + (a['y']-b['y'])**2 + (a['z']-b['z'])**2)

def dist2d(a, b):
    return math.sqrt((a['x']-b['x'])**2 + (a['y']-b['y'])**2)

# ── Finger state helpers ──────────────────────────────────────────────────────
def finger_extended(lm, tip, dip, pip, mcp):
    """Finger is extended if tip is clearly above pip (lower y = higher on screen)"""
    if not all(k in lm for k in [tip, dip, pip, mcp]):
        return False
    # Primary check: tip above pip
    tip_above_pip = lm[tip]['y'] < lm[pip]['y']
    # Secondary: tip above mcp
    tip_above_mcp = lm[tip]['y'] < lm[mcp]['y']
    return tip_above_pip and tip_above_mcp

def finger_curl_ratio(lm, tip, pip):
    """How much finger is curled: 0=straight, 1=fully curled"""
    if tip not in lm or pip not in lm:
        return 0.5
    return max(0, lm[tip]['y'] - lm[pip]['y']) * 10  # positive = curled

def thumb_state(lm):
    """Returns: 'out'=extended sideways, 'up'=pointing up, 'in'=folded"""
    if not all(k in lm for k in [4, 3, 2, 1, 0, 5]):
        return 'in'
    tip = lm[4]
    base = lm[2]
    index_mcp = lm[5]
    wrist = lm[0]
    # Distance from thumb tip to index mcp
    d_to_index = dist2d(tip, index_mcp)
    # Is thumb tip far from palm center?
    palm_center = {'x': (wrist['x']+index_mcp['x'])/2, 'y': (wrist['y']+index_mcp['y'])/2}
    d_from_palm = dist2d(tip, palm_center)
    if d_from_palm > 0.18:
        if tip['y'] < base['y']:
            return 'up'
        return 'out'
    return 'in'

# ── LETTER classifier ─────────────────────────────────────────────────────────
def classify_letter(lm):
    if len(lm) < 15:
        return ("?", 0.5, "Not enough landmarks")

    # Finger states
    I = finger_extended(lm, 8,  7,  6,  5)
    M = finger_extended(lm, 12, 11, 10, 9)
    R = finger_extended(lm, 16, 15, 14, 13)
    P = finger_extended(lm, 20, 19, 18, 17)
    TH = thumb_state(lm)
    T_out = TH in ('out', 'up')
    T_in  = TH == 'in'

    # Key distances
    pinch     = dist2d(lm[4], lm[8])   if 4 in lm and 8 in lm else 0.5
    i_m_gap   = dist2d(lm[8], lm[12])  if 8 in lm and 12 in lm else 0.1
    m_r_gap   = dist2d(lm[12],lm[16])  if 12 in lm and 16 in lm else 0.1
    thumb_idx = dist2d(lm[4], lm[5])   if 4 in lm and 5 in lm else 0.5

    # Curl amounts
    I_curl = finger_curl_ratio(lm, 8, 6)
    M_curl = finger_curl_ratio(lm, 12, 10)

    # Palm direction (z axis)
    palm_toward = lm[0]['z'] < lm[9]['z'] if 0 in lm and 9 in lm else False

    count = sum([I, M, R, P, T_out])

    print(f"  I={I} M={M} R={R} P={P} TH={TH} pinch={pinch:.3f} i_m_gap={i_m_gap:.3f} count={count}")

    # ── CLOSED FIST GROUP (A, S, E, N, M, T) ─────────────────────────
    if not I and not M and not R and not P:
        if T_out and thumb_idx > 0.15:
            if lm[4]['y'] < lm[3]['y']:   # thumb pointing up/side
                return ("A", 0.90, "Fist with thumb on side")
        if T_in and pinch < 0.12:
            return ("S", 0.88, "Fist thumb wrapped over fingers")
        if T_in and pinch > 0.12:
            return ("E", 0.85, "All fingers bent hooks")
        if T_out:
            return ("A", 0.87, "Closed fist thumb side")
        return ("A", 0.83, "Closed fist")

    # ── OPEN HAND GROUP (B, 5) ────────────────────────────────────────
    if I and M and R and P:
        if T_in:
            return ("B", 0.95, "Four fingers up thumb folded - B")
        if T_out:
            return ("5", 0.94, "All five fingers open - 5")

    # ── SINGLE FINGER GROUP (D, G, X, I-letter) ──────────────────────
    if I and not M and not R and not P:
        if T_out and thumb_idx > 0.2:
            return ("L", 0.93, "L shape index up thumb out")
        if T_in and I_curl < 0.1:
            return ("D", 0.88, "Index pointing up - D")
        if T_in and I_curl > 0.2:
            return ("X", 0.85, "Index hooked - X")
        return ("G", 0.83, "Index pointing - G")

    # ── PINKY ONLY (I-letter) ─────────────────────────────────────────
    if not I and not M and not R and P:
        if T_out:
            return ("Y", 0.95, "Thumb and pinky out - Y")
        return ("I", 0.94, "Only pinky up - I")

    # ── THUMB + PINKY (Y) ─────────────────────────────────────────────
    if not I and not M and not R and P and T_out:
        return ("Y", 0.95, "Thumb and pinky - Y")

    # ── TWO FINGER GROUP (U, V, R, H, K) ─────────────────────────────
    if I and M and not R and not P:
        if T_out:
            return ("K", 0.87, "Index middle up with thumb - K")
        if i_m_gap > 0.06:
            return ("V", 0.92, "Index middle spread apart - V")
        if i_m_gap <= 0.06:
            return ("U", 0.91, "Index middle together - U")
        return ("R", 0.82, "Index middle crossed - R")

    # ── THREE FINGER GROUP (W) ────────────────────────────────────────
    if I and M and R and not P:
        if T_in:
            return ("W", 0.92, "Three fingers spread - W")
        return ("W", 0.88, "Three fingers up - W")

    # ── F (pinch + 3 up) ─────────────────────────────────────────────
    if not I and M and R and P and pinch < 0.08:
        return ("F", 0.90, "OK sign index thumb touch - F")

    # ── C (curved) ────────────────────────────────────────────────────
    if not I and not M and not R and not P and pinch > 0.1 and pinch < 0.3:
        return ("C", 0.86, "Curved C shape")

    # ── O (circle) ────────────────────────────────────────────────────
    if pinch < 0.06:
        return ("O", 0.88, "O circle shape")

    # ── Fallback by count ─────────────────────────────────────────────
    if count == 0: return ("A", 0.75, "Closed")
    if count == 1: return ("G", 0.72, "One extended")
    if count == 2: return ("V", 0.72, "Two extended")
    if count == 3: return ("W", 0.72, "Three extended")
    if count == 4: return ("B", 0.72, "Four extended")
    return ("5", 0.72, "All extended")

# ── WORD classifier ───────────────────────────────────────────────────────────
def classify_word(lm):
    if len(lm) < 15:
        return ("?", 0.5, "Not enough landmarks")

    I = finger_extended(lm, 8,  7,  6,  5)
    M = finger_extended(lm, 12, 11, 10, 9)
    R = finger_extended(lm, 16, 15, 14, 13)
    P = finger_extended(lm, 20, 19, 18, 17)
    TH = thumb_state(lm)
    T_out = TH in ('out', 'up')
    T_in  = TH == 'in'

    pinch   = dist2d(lm[4], lm[8])  if 4 in lm and 8 in lm else 0.5
    count   = sum([I, M, R, P, T_out])

    print(f"  [WORD] I={I} M={M} R={R} P={P} TH={TH} pinch={pinch:.3f} count={count}")

    # YES: fist nodding = S shape (closed fist)
    if not I and not M and not R and not P and T_in:
        return ("YES", 0.90, "Closed fist = YES")

    # NO: index + middle snap to thumb
    if I and M and not R and not P and pinch < 0.12:
        return ("NO", 0.89, "Index middle snap to thumb = NO")

    # GOOD: flat hand, all fingers + thumb extended
    if I and M and R and P and T_out:
        return ("GOOD", 0.91, "Open flat hand = GOOD")

    # BAD: similar to good but palm down / away
    if I and M and R and P and T_in:
        return ("BAD", 0.87, "Four fingers up = BAD")

    # HELP: thumb up (thumbs up gesture)
    if T_out and not I and not M and not R and not P:
        return ("HELP", 0.92, "Thumbs up = HELP")

    # HELLO: open hand wave (all fingers up)
    if I and M and R and P and T_out:
        return ("HELLO", 0.90, "Open hand wave = HELLO")

    # PLEASE: flat hand on chest (all extended)
    if I and M and R and P and T_in:
        return ("PLEASE", 0.85, "Flat hand = PLEASE")

    # SORRY: fist (closed hand)
    if not I and not M and not R and not P:
        return ("SORRY", 0.83, "Closed fist = SORRY")

    # THANK YOU: flat hand moves out (fingers extended)
    if I and M and not R and not P:
        return ("THANK YOU", 0.84, "Two fingers = THANK YOU")

    # MORE: fingertips together
    if pinch < 0.08:
        return ("MORE", 0.85, "Fingertips together = MORE")

    # Fallback
    if count >= 4:
        return ("GOOD", 0.75, "Open hand")
    if count == 0:
        return ("YES", 0.75, "Closed fist")
    return ("HELP", 0.70, "Gesture detected")

# ── Flask routes ──────────────────────────────────────────────────────────────
@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        data = request.get_json()
        prompt = data['messages'][0]['content']
        mode = data.get('mode', 'letter')

        lm = parse_landmarks(prompt)
        print(f"[LANDMARKS] {len(lm)} points | mode={mode}")

        if mode == 'word':
            word, conf, desc = classify_word(lm)
            result = json.dumps({"word": word, "confidence": conf, "description": desc, "alternatives": []})
        else:
            letter, conf, desc = classify_letter(lm)
            result = json.dumps({"letter": letter, "confidence": conf, "description": desc, "alternatives": []})

        print(f"[RESULT] {result}")
        return jsonify({"content": [{"text": result}]})

    except Exception as e:
        print("[ERROR] " + str(e))
        import traceback; traceback.print_exc()
        fallback = json.dumps({"letter": "?", "confidence": 0.9, "description": str(e), "alternatives": []})
        return jsonify({"content": [{"text": fallback}]})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    print("")
    print("  *** SERVER RUNNING — Letters + Words Mode ***")
    print("  URL: http://localhost:8080")
    print("  Open index.html in Chrome")
    print("")
    app.run(debug=False, port=8080, host='127.0.0.1', use_reloader=False, threaded=True)
