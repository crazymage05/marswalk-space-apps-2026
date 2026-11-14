"""W7 metrics: seam jump ratios, EMD to source, 3x3 previews. python tools/w7_tex_metrics.py"""
import numpy as np, json
from PIL import Image
from scipy.stats import wasserstein_distance
T='demo/twin/tex/'
def lum(p): return np.asarray(Image.open(p).convert('L'),np.float64)/255
def jumps(a):
    dr=np.abs(np.diff(np.vstack([a,a[:1]]),axis=0)).mean(1)   # row k -> k+1 (last wraps to 0)
    dc=np.abs(np.diff(np.hstack([a,a[:,:1]]),axis=1)).mean(0)
    mr,mc=np.median(dr),np.median(dc)
    return dict(row_centre=dr[511]/mr,col_centre=dc[511]/mc,row_wrap=dr[1023]/mr,col_wrap=dc[1023]/mc,
                row_max=dr.max()/mr,col_max=dc.max()/mc)
def emd(a,ex):
    ex=(ex-ex.min())/(ex.max()-ex.min())
    # compare normalised-to-percentile luminance (source z vs tile z), 1-99 percentile stretch
    return wasserstein_distance(a.ravel()[::7],ex.ravel()[::7])
out={}
for m in ['bedrock','sand','pebbly']:
    ex=np.load(f'runs/w7_{m}_ex.npy'); lo,hi=np.percentile(ex,[1,99]); exz=np.clip((ex-lo)/(hi-lo),0,1)
    out[m]={}
    for tag,d in [('before',T+'old/'),('after',T)]:
        res={}
        for kind in ['albedo','normal','rough']:
            im=np.asarray(Image.open(f'{d}{m}_{kind}.jpg').convert('L' if kind!='normal' else 'RGB'),np.float64)/255
            if kind=='normal': res['normal']={'row':[jumps(im[...,c])['row_centre'] for c in range(2)],'col':[jumps(im[...,c])['col_centre'] for c in range(2)]}
            else: res[kind]=jumps(im)
        a=lum(f'{d}{m}_albedo.jpg'); lo2,hi2=np.percentile(a,[1,99]); az=np.clip((a-lo2)/(hi2-lo2),0,1)
        res['emd_z']=wasserstein_distance(az.ravel()[::5],exz.ravel()[::5])
        out[m][tag]=res
        t=np.tile(np.asarray(Image.open(f'{d}{m}_albedo.jpg')),(3,3,1))
        Image.fromarray(t).resize((1536,1536),Image.LANCZOS).save(f'docs/figures/w7_tiled_{m}_{tag}.png')
json.dump(out,open('runs/w7_metrics.json','w'),indent=1)
f=lambda x:f'{x:.2f}'
for m in out:
    for tag in ['before','after']:
        r=out[m][tag]; A=r['albedo']
        print(m,tag,'albedo rc',f(A['row_centre']),'cc',f(A['col_centre']),'rw',f(A['row_wrap']),'cw',f(A['col_wrap']),
          '| rough rc/cc',f(r['rough']['row_centre']),f(r['rough']['col_centre']),'| normal rc',[f(v) for v in r['normal']['row']],'cc',[f(v) for v in r['normal']['col']],'| emd',f'{r["emd_z"]:.4f}')
