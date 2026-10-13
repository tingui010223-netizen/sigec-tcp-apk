#!/usr/bin/env python3
"""
Prepara las copias de los 3 proyectos que van DENTRO de la APK.
Los archivos originales NO se tocan (siguen igual cuando los vendes sueltos).

  almacen -> se esconde el botón "Exportar día" (ya no hace falta, pasa solo a sigec)
  cuadre  -> se quita el código propio y se usa la licencia de Almacén
  sigec   -> igual que cuadre, y además trae solo los productos y las ventas
             de los días que se confirman en Almacén (sin exportar ni importar)

Uso: python3 preparar_apk.py almacen|cuadre|sigec  origen.html  destino.html
"""
import sys

MODOS = ("almacen", "cuadre", "sigec")
if len(sys.argv) != 4 or sys.argv[1] not in MODOS:
    sys.exit("Uso: preparar_apk.py [almacen|cuadre|sigec] origen.html destino.html")

modo, origen, destino = sys.argv[1:]
html = open(origen, encoding="utf-8").read()

REQUERIDAS = {
    "almacen": ("</head>", 'id="ipvExportBtn"'),
    "cuadre": ("</head>", "</body>", "iniciarApp("),
    "sigec": ("</head>", "</body>", "mostrarAppLicenciadoTCP(", "function buscarProductoPorCodTCP("),
}
# Si el archivo cambió y ya no encaja, la compilación falla (no sale una APK mala)
for marca in REQUERIDAS[modo]:
    if marca not in html:
        sys.exit("ERROR: en %s no se encontró %r. No se puede preparar la APK." % (origen, marca))

# ---------------------------------------------------------------- ALMACÉN
if modo == "almacen":
    css = """<style>
/* APK: el botón Exportar día se esconde, las ventas pasan solas a sigec */
#ipvExportBtn{display:none!important}
</style>
"""
    html = html.replace("</head>", css + "</head>", 1)
    open(destino, "w", encoding="utf-8").write(html)
    print("Listo:", destino)
    sys.exit(0)

# ------------------------------------------------------- CUADRE y SIGEC
LLAMADA = {
    "cuadre": "iniciarApp(nombreNegocio());",
    "sigec": "mostrarAppLicenciadoTCP(nombreNegocio()); sincronizar();",
}[modo]

CSS = """<style>
/* APK: la licencia la maneja Almacén, se esconden los botones de cambiar licencia */
[onclick^="cambiarLicencia"]{display:none!important}
</style>
"""

SYNC = r"""
  /* ---- Almacén -> sigec: productos y ventas de los días confirmados ---- */
  function leerAlmacen(){
    try{ var s=JSON.parse(localStorage.getItem('almacen_app_v1')||'null'); return (s&&typeof s==='object')?s:null; }
    catch(x){ return null; }
  }
  function avisar(txt){
    try{
      var t=document.createElement('div');
      t.textContent=txt;
      t.style.cssText='position:fixed;left:12px;right:12px;bottom:calc(16px + env(safe-area-inset-bottom,0px));z-index:2147483000;background:#1A2C40;color:#fff;border:1px solid #1FD9C4;border-radius:10px;padding:12px 14px;font:14px/1.4 system-ui,sans-serif;text-align:center;box-shadow:0 6px 20px rgba(0,0,0,.4)';
      document.body.appendChild(t);
      setTimeout(function(){ if(t.parentNode) t.parentNode.removeChild(t); },7000);
    }catch(x){}
  }
  function stockConfirmado(p,A){
    var s=Number(p.init)||0, c=A.confirmedDays||{};
    (A.movements||[]).forEach(function(m){ if(m.code===p.code){ s+=(m.type==='E'?1:-1)*(Number(m.qty)||0); } });
    (A.sales||[]).forEach(function(v){ if(v.code===p.code && c[v.date]){ s-=Number(v.qty)||0; } });
    return s;
  }
  function sincronizar(){
    try{
      if(!almacenActivo()) return;
      var A=leerAlmacen(); if(!A) return;
      if(typeof DATA==='undefined' || !DATA) return;
      var confirmados=A.confirmedDays||{};
      var base=null;
      try{ base=JSON.parse(localStorage.getItem('sigec_sync_base')||'null'); }catch(e){}
      if(!Array.isArray(base)){ base=Object.keys(confirmados); localStorage.setItem('sigec_sync_base',JSON.stringify(base)); }
      if(!DATA.almacenSync || typeof DATA.almacenSync!=='object') DATA.almacenSync={};
      var log=DATA.almacenSync;
      var tipo=(DATA.perfil&&DATA.perfil.tipoActividad)||'productos';
      var conInventario=(tipo==='productos'||tipo==='ambos');
      var n={prodNuevos:0,precios:0,dias:0,cambiados:0}, tocado=false, creados={};

      /* 1) Productos de Almacén: los nuevos se crean; en los que ya existen se pone el precio de Almacén */
      var infoProd={};
      (A.products||[]).forEach(function(p){
        infoProd[p.code]=p;
        var precio=Number(p.price)||0;
        var prod=buscarProductoPorCodTCP(p.code,p.desc);
        if(!prod){
          prod={id:uid(),codigo:p.code||'',descripcion:p.desc||p.code||'',unidad:p.unit||'',costoUnitario:0,margenPct:0,precioVenta:precio,existencia:stockConfirmado(p,A)};
          DATA.productos.push(prod); creados[prod.id]=true; n.prodNuevos++; tocado=true;
        }else if(precio>0 && Number(prod.precioVenta)!==precio){
          prod.precioVenta=precio; n.precios++; tocado=true;
        }
      });

      /* 2) Ventas de cada día confirmado en Almacén */
      Object.keys(confirmados).sort().forEach(function(fecha){
        var reg=log[fecha];
        if(!reg && base.indexOf(fecha)>=0) return;           /* días de antes de esta versión: ya los pasaste a mano */
        var por={};
        (A.sales||[]).forEach(function(v){ if(v.date===fecha){ por[v.code]=(por[v.code]||0)+(Number(v.qty)||0); } });
        var lineas=[];
        Object.keys(por).sort().forEach(function(code){
          if(por[code]>0){ var pr=infoProd[code]||{}; lineas.push({cod:code,producto:pr.desc||code,qty:por[code],precio:Number(pr.price)||0}); }
        });
        if(lineas.length===0) return;
        var firma=lineas.map(function(l){ return l.cod+':'+l.qty+':'+l.precio; }).join('|');
        if(reg){
          if(reg.manual || reg.firma===firma) return;
          /* el día se desbloqueó y se confirmó otra vez con cambios: se deshace lo anterior y se pasa de nuevo */
          DATA.ingresos=DATA.ingresos.filter(function(x){ return x.id!==reg.ingresoId; });
          DATA.movInventario=DATA.movInventario.filter(function(m){ return (reg.movIds||[]).indexOf(m.id)<0; });
          (reg.desc||[]).forEach(function(d){
            var pr=DATA.productos.filter(function(q){ return q.id===d.id; })[0];
            if(pr) pr.existencia=(Number(pr.existencia)||0)+d.qty;
          });
          n.cambiados++;
        }else{
          var yaHay=DATA.ingresos.filter(function(x){ return x.fecha===fecha && /^Ventas IPV del día/.test(x.concepto||''); })[0];
          if(yaHay){ log[fecha]={manual:true,ingresoId:yaHay.id,firma:firma}; tocado=true; return; }   /* ya lo importaste a mano */
        }
        var total=0, costo=0, sinCosto=0, movIds=[], desc=[];
        lineas.forEach(function(l){
          var prod=buscarProductoPorCodTCP(l.cod,l.producto);
          total+=l.qty*l.precio;
          if(prod){ costo+=(Number(prod.costoUnitario)||0)*l.qty; } else { sinCosto++; }
          if(prod && conInventario){
            if(!creados[prod.id]){ prod.existencia=(Number(prod.existencia)||0)-l.qty; desc.push({id:prod.id,qty:l.qty}); }
            var mid=uid();
            DATA.movInventario.push({id:mid,fecha:fecha,productoId:prod.id,tipo:'salida',cantidad:l.qty,motivo:'Importado de Almacén (automático)',ipvCosto:true});
            movIds.push(mid);
          }
        });
        var ingId=uid();
        DATA.ingresos.push({id:ingId,fecha:fecha,clienteId:'',concepto:'Ventas IPV del día — '+(A.bizName||'Almacén'),importe:total,productoId:'',cantidadProducto:0,costoVenta:costo,lineasSinCosto:sinCosto,auto:true});
        log[fecha]={ingresoId:ingId,firma:firma,movIds:movIds,desc:desc};
        n.dias++; tocado=true;
      });

      if(tocado){
        guardarDatos();
        try{ renderIngresos(); }catch(e){}
        try{ renderDashboard(); }catch(e){}
        try{ renderInventario(); }catch(e){}
        try{ poblarSelectProductos(); }catch(e){}
      }
      var partes=[];
      if(n.dias) partes.push(n.dias+' día(s) de ventas');
      if(n.cambiados) partes.push(n.cambiados+' día(s) corregido(s)');
      if(n.prodNuevos) partes.push(n.prodNuevos+' producto(s) nuevo(s)');
      if(n.precios) partes.push(n.precios+' precio(s) actualizado(s)');
      if(partes.length) avisar('Pasó de Almacén a sigec: '+partes.join(', '));
    }catch(err){
      try{ console.error('Sincronizar Almacén:',err); }catch(x){}
    }
  }
  window.sincronizarDesdeAlmacen=sincronizar;
"""

JS = r"""<script>
/* APK: entrar usando la licencia de Almacén (sin pedir otro código) */
(function(){
  function almacenActivo(){
    try{
      var e=localStorage.getItem('tmg_license_exp')||'';
      var h=new Date().toISOString().slice(0,10);
      return !!e && e>=h;
    }catch(x){ return false; }
  }
  function nombreNegocio(){
    try{
      var s=JSON.parse(localStorage.getItem('almacen_app_v1')||'{}');
      return String(s.bizName||'').trim()||'Mi negocio';
    }catch(x){ return 'Mi negocio'; }
  }
  function bloquear(){
    var d=document.createElement('div');
    d.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;z-index:2147483647;background:#0D1B2A;color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:24px;font-family:system-ui,sans-serif';
    d.innerHTML='<div style="font-size:42px;margin-bottom:12px">\uD83D\uDD12</div>'
      +'<div style="font-size:18px;font-weight:700;margin-bottom:8px">Activaci\u00F3n requerida</div>'
      +'<div style="font-size:15px;line-height:1.45;max-width:320px">Primero activa <b>Almac\u00E9n</b> con tu c\u00F3digo. Toca los 3 puntitos arriba a la derecha y entra a <b>Almac\u00E9n</b>.</div>';
    document.body.appendChild(d);
  }
__SYNC__
  function arrancar(){
    if(!almacenActivo()){ bloquear(); return; }
    __LLAMADA__
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',arrancar);
  else arrancar();
})();
</script>
"""
JS = JS.replace("__SYNC__", SYNC if modo == "sigec" else "").replace("__LLAMADA__", LLAMADA)

html = html.replace("</head>", CSS + "</head>", 1)
i = html.rfind("</body>")
html = html[:i] + JS + html[i:]

open(destino, "w", encoding="utf-8").write(html)
print("Listo:", destino)