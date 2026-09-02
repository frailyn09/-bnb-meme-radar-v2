from flask import Flask, jsonify, request, render_template_string
import requests
import time

app = Flask(__name__)

DEX = "https://api.dexscreener.com/latest/dex"
CHAIN = "bsc"

HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BNB Meme Radar</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0b0d10;color:#fff;margin:0;padding:18px}
h1{font-size:26px}
.card{background:#151922;border-radius:16px;padding:16px;margin:12px 0}
input,button{width:100%;box-sizing:border-box;padding:14px;border-radius:12px;border:0;margin-top:8px;font-size:16px}
button{background:#f0b90b;color:#111;font-weight:700}
.score{font-size:32px;font-weight:800}
.good{color:#43d17a}.warn{color:#ffd166}.bad{color:#ff6464}
.small{color:#aeb4c0;font-size:13px}
</style>
</head>
<body>
<h1>🟡 BNB Meme Radar</h1>
<p class="small">Detector de oportunidades especulativas en BNB Chain</p>

<div class="card">
<input id="token" placeholder="Pega aquí el contrato 0x...">
<button onclick="scan()">ANALIZAR TOKEN</button>
</div>

<div id="result"></div>

<script>
async function scan(){
 const token=document.getElementById("token").value.trim();
 if(!token){alert("Introduce un contrato");return}
 document.getElementById("result").innerHTML="<div class='card'>Analizando...</div>";
 const r=await fetch("/api/scan?token="+encodeURIComponent(token));
 const d=await r.json();
 if(d.error){
   document.getElementById("result").innerHTML="<div class='card bad'>"+d.error+"</div>";
   return;
 }
 let cls=d.score>=80?"good":d.score>=65?"warn":"bad";
 document.getElementById("result").innerHTML=`
 <div class="card">
   <div class="small">SCORE</div>
   <div class="score ${cls}">${d.score}/100</div>
   <h2>${d.label}</h2>
   <p><b>Precio:</b> $${d.price}</p>
   <p><b>Liquidez:</b> $${d.liquidity}</p>
   <p><b>Market Cap:</b> $${d.market_cap}</p>
   <p><b>Volumen 24h:</b> $${d.volume}</p>
   <p><b>Compras:</b> ${d.buys} &nbsp; <b>Ventas:</b> ${d.sells}</p>
   <p><b>Cambio 24h:</b> ${d.change}%</p>
 </div>
 <div class="card">
   <h3>Señales</h3>
   ${d.reasons.map(x=>"<p>• "+x+"</p>").join("")}
 </div>`;
}
</script>
</body>
</html>
"""

def money(x):
    if x is None:
        return "0"
    x=float(x)
    if x >= 1_000_000:
        return f"{x/1_000_000:.2f}M"
    if x >= 1_000:
        return f"{x/1_000:.1f}K"
    return f"{x:.2f}"

def analyze(p):
    liq=float(p.get("liquidity",{}).get("usd") or 0)
    vol=float(p.get("volume",{}).get("h24") or 0)
    change=float(p.get("priceChange",{}).get("h24") or 0)
    mc=float(p.get("marketCap") or p.get("fdv") or 0)

    tx=p.get("txns",{}).get("h24",{})
    buys=int(tx.get("buys") or 0)
    sells=int(tx.get("sells") or 0)
    total=buys+sells

    score=0
    reasons=[]

    if liq >= 100000: score += 25; reasons.append("Liquidez fuerte")
    elif liq >= 30000: score += 18; reasons.append("Liquidez aceptable")
    elif liq >= 10000: score += 10; reasons.append("Liquidez baja")

    if mc > 0:
        ratio=liq/mc
        if ratio >= .15:
            score += 15
            reasons.append("Buena relación liquidez/market cap")
        elif ratio >= .07:
            score += 10
            reasons.append("Relación liquidez/MC razonable")

    if total:
        sell_ratio=sells/total
        if sells >= 50 and buys > 0:
            reasons.append("Hay actividad vendedora elevada")
        if buys > sells:
            score += 20
            reasons.append("Las compras superan a las ventas")
        elif sells > buys and sell_ratio > .60:
            score += 4
            reasons.append("Muchas ventas: posible presión vendedora")
        else:
            score += 10

    if vol >= liq*2 and liq > 0:
        score += 15
        reasons.append("Volumen elevado respecto a liquidez")
    elif vol >= liq and liq > 0:
        score += 9

    if 2 <= change <= 25:
        score += 15
        reasons.append("Momentum positivo sin subida extrema")
    elif change > 25:
        score += 6
        reasons.append("Subida fuerte: riesgo de entrada tardía")
    elif change >= 0:
        score += 8
    else:
        score += 4
        reasons.append("Precio débil en 24h")

    score=min(100,int(score))

    if score >= 80:
        label="STRONG"
    elif score >= 65:
        label="WATCH"
    elif score >= 50:
        label="NEUTRAL"
    else:
        label="AVOID"

    return score,label,reasons

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/api/scan")
def scan():
    token=request.args.get("token","").strip()

    if not token.startswith("0x") or len(token)!=42:
        return jsonify({"error":"Contrato BSC no válido"}),400

    try:
        url=f"{DEX}/tokens/{token}"
        r=requests.get(url,timeout=15)
        data=r.json()
        pairs=data.get("pairs") or []

        bsc=[p for p in pairs if p.get("chainId")==CHAIN]

        if not bsc:
            return jsonify({"error":"No encontré pares BSC para este contrato"}),404

        p=max(
            bsc,
            key=lambda x: float(x.get("liquidity",{}).get("usd") or 0)
        )

        score,label,reasons=analyze(p)

        tx=p.get("txns",{}).get("h24",{})

        return jsonify({
            "score":score,
            "label":label,
            "reasons":reasons,
            "price":p.get("priceUsd") or "0",
            "liquidity":money(p.get("liquidity",{}).get("usd")),
            "market_cap":money(p.get("marketCap") or p.get("fdv")),
            "volume":money(p.get("volume",{}).get("h24")),
            "buys":tx.get("buys") or 0,
            "sells":tx.get("sells") or 0,
            "change":p.get("priceChange",{}).get("h24") or 0,
            "pair":p.get("pairAddress"),
            "dex":p.get("dexId")
        })

    except Exception as e:
        return jsonify({"error":f"Error consultando DEX Screener: {str(e)}"}),500

@app.route("/health")
def health():
    return "OK"

if __name__=="__main__":
    app.run(host="0.0.0.0",port=10000)
