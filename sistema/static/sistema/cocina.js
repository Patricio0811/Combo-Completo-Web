(() => {
  const tablero = document.getElementById("tablero");
  const red = document.getElementById("estado-red");
  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
  const ETQ = { pendiente: "Preparar", preparacion: "Marcar lista" };
  const SIG = { pendiente: "preparacion", preparacion: "lista" };
  const abiertas = new Set();   // comandas ampliadas: se recuerdan aunque la pantalla se actualice cada 2 s
  let base = 0;

  const mmss = (s) => String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  const el = (tag, clase, texto) => { const e = document.createElement(tag); if (clase) e.className = clase; if (texto !== undefined) e.textContent = texto; return e; };

  async function cambiar(id, estado) {
    await fetch(`/api/comandas/${id}/estado/`, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify({ estado }) });
    cargar();
  }

  // Todo texto del pedido (observaciones, nombres, detalles) se inserta con textContent: nunca se interpreta como HTML.
  function tarjeta(c) {
    const abierta = abiertas.has(c.id);
    const a = el("article", "ticket " + c.estado + (abierta ? " abierto" : ""));
    if (c.segundos > 600) a.classList.add("tarde");
    a.dataset.seg = c.segundos;

    const h = el("header");
    h.append(el("strong", "", "#" + c.pedido), el("span", "etq", c.canal), el("span", "", c.ref));
    const t = el("time", "tiempo", mmss(c.segundos)); h.append(t);

    const ul = el("ul", "productos-comanda");
    c.items.forEach((i) => {
      const li = el("li");
      li.append(el("span", "linea-prod", `${i.c} × ${i.n}`));
      if (abierta) {   // vista ampliada: de qué está hecho cada producto
        const det = el("div", "detalle-prod");
        det.append(el("p", "", i.d ? i.d : "Sin detalle cargado para este producto."));
        if (i.ins.length) det.append(el("p", "insumos", "Insumos: " + i.ins.map((x) => `${x.n} ${x.c} ${x.u}`).join(" · ")));
        li.append(det);
      }
      ul.append(li);
    });
    a.append(h, ul);

    if (c.obs) { const o = el("p", "obs", "Obs.: " + c.obs); a.append(o); }
    if (abierta) a.append(el("p", "ayuda", `Llegó a las ${c.hora} · ${c.items.reduce((s, i) => s + i.c, 0)} unidades en total`));

    const f = el("footer");
    const ver = el("button", "btn chico", abierta ? "Ocultar detalle" : "Ver detalle");
    ver.type = "button"; ver.setAttribute("aria-expanded", abierta);
    ver.addEventListener("click", () => { abierta ? abiertas.delete(c.id) : abiertas.add(c.id); cargar(); });
    const b = el("button", "btn primario", ETQ[c.estado]);
    b.addEventListener("click", () => { abiertas.delete(c.id); cambiar(c.id, SIG[c.estado]); });
    f.append(ver, b); a.append(f);
    return a;
  }

  async function cargar() {
    try {
      const r = await fetch("/api/comandas/"); if (!r.ok) throw 0;
      const d = await r.json(); base = Date.now();
      const ids = new Set(d.comandas.map((c) => c.id));
      abiertas.forEach((id) => { if (!ids.has(id)) abiertas.delete(id); });   // comanda que ya salió de la lista
      tablero.replaceChildren();
      if (!d.comandas.length) tablero.append(el("p", "vacio", "Sin comandas pendientes."));
      d.comandas.forEach((c) => tablero.append(tarjeta(c)));   // ya vienen por hora de llegada
      red.textContent = "Actualizado " + new Date().toLocaleTimeString("es-CL"); red.classList.remove("mal");
    } catch (_) { red.textContent = "Sin conexión con el servidor. Reintentando…"; red.classList.add("mal"); }
  }
  setInterval(() => {
    document.querySelectorAll(".ticket").forEach((a) => {
      const s = Number(a.dataset.seg) + Math.round((Date.now() - base) / 1000);
      a.querySelector(".tiempo").textContent = mmss(s); a.classList.toggle("tarde", s > 600);
    });
  }, 1000);
  cargar(); setInterval(cargar, 2000);   // menos de 4 s (RNF03)
})();
