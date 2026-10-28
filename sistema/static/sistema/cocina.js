(() => {
  const tablero = document.getElementById("tablero");
  const red = document.getElementById("estado-red");
  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
  const ETQ = { pendiente: "Preparar", preparacion: "Marcar lista" };
  const SIG = { pendiente: "preparacion", preparacion: "lista" };
  let base = 0;

  const mmss = (s) => String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");

  async function cambiar(id, estado) {
    await fetch(`/api/comandas/${id}/estado/`, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify({ estado }) });
    cargar();
  }

  // Todo texto del pedido (observaciones, nombres) se inserta con textContent: nunca se interpreta como HTML.
  function tarjeta(c) {
    const a = document.createElement("article"); a.className = "ticket " + c.estado;
    if (c.segundos > 600) a.classList.add("tarde");
    a.dataset.seg = c.segundos;
    const h = document.createElement("header");
    const n = document.createElement("strong"); n.textContent = "#" + c.pedido;
    const canal = document.createElement("span"); canal.className = "etq"; canal.textContent = c.canal;
    const ref = document.createElement("span"); ref.textContent = c.ref;
    const t = document.createElement("time"); t.className = "tiempo"; t.textContent = mmss(c.segundos);
    h.append(n, canal, ref, t);
    const ul = document.createElement("ul");
    c.items.forEach((i) => { const li = document.createElement("li"); li.textContent = `${i.c} × ${i.n}`; ul.append(li); });
    a.append(h, ul);
    if (c.obs) { const o = document.createElement("p"); o.className = "obs"; o.textContent = "Obs.: " + c.obs; a.append(o); }
    const f = document.createElement("footer");
    const hora = document.createElement("small"); hora.textContent = "Llegó " + c.hora;
    const b = document.createElement("button"); b.className = "btn primario"; b.textContent = ETQ[c.estado];
    b.addEventListener("click", () => cambiar(c.id, SIG[c.estado]));
    f.append(hora, b); a.append(f);
    return a;
  }

  async function cargar() {
    try {
      const r = await fetch("/api/comandas/"); if (!r.ok) throw 0;
      const d = await r.json(); base = Date.now();
      tablero.replaceChildren();
      if (!d.comandas.length) { const p = document.createElement("p"); p.className = "suave"; p.textContent = "Sin comandas pendientes."; tablero.append(p); }
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
