"""Plan routes by real clicks on the twin's 3D map and walk one.  usage: python tools/twin_manual_plan.py <name> <width> <height>
(serve demo/twin first: python -m http.server 8765 --bind 127.0.0.1 -d demo/twin)"""
import sys, os, json
from playwright.sync_api import sync_playwright
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT=os.path.join(ROOT, "runs", "twin_check", sys.argv[1]); os.makedirs(OUT, exist_ok=True)
W,H=int(sys.argv[2]),int(sys.argv[3]); res=[]
with sync_playwright() as p:
    b=p.chromium.launch(channel="chrome",headless=True,args=["--enable-gpu","--ignore-gpu-blocklist","--use-angle=metal"])
    pg=b.new_page(viewport={"width":W,"height":H})
    pg.goto("http://127.0.0.1:8765/twin.html"); pg.wait_for_function("document.getElementById('loading').hidden===true",timeout=180000); pg.wait_for_timeout(2000)
    pg.uncheck("#lyPhotos"); pg.click("#btnClear"); pg.wait_for_timeout(400)
    pg.locator("#view").scroll_into_view_if_needed(); pg.wait_for_timeout(400)
    bb=pg.locator("#view canvas").first.bounding_box()
    pairs=[((0.40,0.40),(0.62,0.62)),((0.30,0.55),(0.55,0.35)),((0.50,0.30),(0.50,0.70))]
    for k,(a,c) in enumerate(pairs):
        for fx,fy in (a,c):
            x,y=bb["x"]+bb["width"]*fx, bb["y"]+bb["height"]*fy
            pg.mouse.move(x,y); pg.mouse.down(); pg.mouse.up(); pg.wait_for_timeout(1200)
        st={i:pg.locator("#"+i).inner_text() for i in ["sDist","sTime","sClimb","sSteep","sDose"]}
        stat=pg.locator("#status").inner_text()
        if "steeper" in stat:      # find the refused point's cell: hover it, read the inspector's cell id
            fx,fy=c if pg.locator("#hint").inner_text().startswith("Now click where") else a
            pg.mouse.move(bb["x"]+bb["width"]*fx, bb["y"]+bb["height"]*fy); pg.wait_for_timeout(900)
            st["refused_cell"]=int(pg.evaluate("document.getElementById('cellCard').dataset.cell"))
        res.append({"pair":k,"stats":st,"status":pg.locator("#status").inner_text(),"hint":pg.locator("#hint").inner_text()})
        pg.screenshot(path=f"{OUT}/manual_{k}.png")
    # then walk the manual route
    pg.click("#btnWalk"); pg.wait_for_function("window.__walk.on===true",timeout=240000); pg.wait_for_timeout(5000)
    res.append({"walk_s":pg.evaluate("window.__walk.s"),"wDist":pg.locator("#wDist").inner_text()}); pg.screenshot(path=f"{OUT}/manual_walk.png")
    b.close()
print(json.dumps(res,indent=1,ensure_ascii=False))
