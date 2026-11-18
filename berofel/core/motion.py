"""Curvas de movimento por bloco (tempos relativos à timeline do próprio bloco).

As funções aqui não importam Qt nem FFmpeg: são testáveis em projetos offline.
"""
from __future__ import annotations

import math

ANIMATABLE = ('pos_x', 'pos_y', 'scale', 'opacity', 'volume', 'rotation')


def _validate(field, points):
    if field not in ANIMATABLE:
        raise ValueError(f'Propriedade não animável: {field}')
    if not isinstance(points, list):
        raise ValueError('Keyframes devem ser uma lista.')
    records = []
    for point in points:
        t = float(point['t']); value = float(point['value'])
        easing = str(point.get('easing', 'linear'))
        if not (math.isfinite(t) and math.isfinite(value)) or t < 0:
            raise ValueError('Keyframe inválido.')
        if easing not in ('linear', 'ease-in', 'ease-out', 'smooth', 'bezier'):
            raise ValueError(f'Curva desconhecida: {easing}')
        record={'t': t, 'value': value, 'easing': easing}
        if easing=='bezier':
            c1=float(point.get('bezier_c1',.1));c2=float(point.get('bezier_c2',.9))
            if not (math.isfinite(c1) and math.isfinite(c2) and 0<=c1<=1 and 0<=c2<=1):
                raise ValueError('Controles Bézier devem estar entre 0 e 1.')
            record.update(bezier_c1=c1,bezier_c2=c2)
        records.append(record)
    records.sort(key=lambda p: p['t'])
    if any(b['t']-a['t'] < 1e-5 for a,b in zip(records, records[1:])):
        raise ValueError('Dois keyframes não podem ocupar o mesmo instante.')
    return records


def interpolate(points, at, default):
    """Interpolação com valor nos extremos e ease após o ponto inicial."""
    if not points: return float(default)
    points = sorted(points, key=lambda p: p['t'])
    t=float(at)
    if t <= points[0]['t']: return float(points[0]['value'])
    for a,b in zip(points, points[1:]):
        if t <= b['t']:
            fraction = max(0.0, min(1.0,(t-a['t'])/max(1e-8, b['t']-a['t'])))
            mode=a.get('easing','linear')
            if mode == 'ease-in': fraction *= fraction
            elif mode == 'ease-out': fraction = 1-(1-fraction)**2
            elif mode == 'smooth': fraction = fraction*fraction*(3-2*fraction)
            elif mode == 'bezier':
                u=fraction
                c1=float(a.get('bezier_c1',.1));c2=float(a.get('bezier_c2',.9))
                fraction=3*(1-u)*(1-u)*u*c1+3*(1-u)*u*u*c2+u*u*u
            return float(a['value'])+(float(b['value'])-float(a['value']))*fraction
    return float(points[-1]['value'])


def value_at(clip, field, at):
    return interpolate(clip.keyframes.get(field, []), at, getattr(clip,field))


def put_keyframe(clip, field, at, value=None, easing='linear',
                 bezier_c1=.1,bezier_c2=.9):
    old=_validate(field, clip.keyframes.get(field, []))
    at=max(0.0,min(float(clip.duration),float(at)))
    if value is None: value = interpolate(old, at, getattr(clip,field))
    record={'t': round(at,5), 'value': float(value), 'easing': easing}
    if easing=='bezier':
        record.update(bezier_c1=float(bezier_c1),bezier_c2=float(bezier_c2))
    _validate(field,[record])
    new=[p for p in old if abs(p['t']-at)>1e-4]+[record]
    clip.keyframes[field]=_validate(field,new)
    return record


def delete_keyframe(clip, field, at, tolerance=.035):
    pts=clip.keyframes.get(field, [])
    new=[p for p in pts if abs(float(p['t'])-at)>tolerance]
    if len(new)==len(pts):return False
    clip.keyframes[field]=new
    return True


def slice_keyframes(keyframes, start, end):
    """Corta uma curva em [start,end], incluindo valor calculado nas bordas."""
    result={}
    for field, points in keyframes.items():
        if field not in ANIMATABLE or not points: continue
        pts=_validate(field, points)
        first=interpolate(pts,start,pts[0]['value'])
        last=interpolate(pts,end,pts[-1]['value'])
        segment=[{'t':0.0,'value':first,'easing':'linear'}]
        for point in pts:
            if start + 1e-5 < point['t'] < end-1e-5:
                segment.append({**point,'t':round(point['t']-start,5)})
        if end-start > 1e-5:
            segment.append({'t':round(end-start,5),'value':last,'easing':'linear'})
        result[field]=_validate(field,segment)
    return result


def retime_keyframes(keyframes, ratio):
    return {field:[{**p,'t':round(float(p['t'])*ratio,5)} for p in pts]
            for field,pts in keyframes.items()}


def ff_expr(clip, field, var='t', time_offset=0.0, value_factor=1.0):
    """Expressão FFmpeg com interpolação por trechos e curvas sem scripts pesados.

    time_offset aplica a janela local de prévia sobre os keyframes originais.
    """
    points=clip.keyframes.get(field, [])
    if not points:return f'{float(getattr(clip,field))*value_factor:.8f}'
    points=_validate(field,points)
    v=lambda p: f'{float(p["value"])*value_factor:.8f}'
    t=lambda p: f'{float(p["t"])-time_offset:.8f}'
    expr=v(points[-1])
    for a,b in reversed(list(zip(points,points[1:]))):
        u=f'max(0,min(1,({var}-{t(a)})/{max(1e-6,b["t"]-a["t"]):.8f}))'
        ease=a.get('easing','linear')
        if ease=='ease-in': f=f'({u})*({u})'
        elif ease=='ease-out':f=f'(1-(1-({u}))*(1-({u})))'
        elif ease=='smooth':f=f'({u})*({u})*(3-2*({u}))'
        elif ease=='bezier':
            c1=float(a.get('bezier_c1',.1));c2=float(a.get('bezier_c2',.9))
            f=f'(3*(1-({u}))*(1-({u}))*({u})*{c1:.8f}+' \
              f'3*(1-({u}))*({u})*({u})*{c2:.8f}+({u})*({u})*({u}))'
        else:f=u
        expr=f'if(lt({var},{t(b)}),({v(a)}+({v(b)}-{v(a)})*({f})),{expr})'
    return f'if(lt({var},{t(points[0])}),{v(points[0])},{expr})'
