(() => {
  const productos = JSON.parse(document.getElementById("datos-productos").textContent);
  const $ = (id) => document.getElementById(id);
  const clp = (n) => "$" + Math.round(n).toLocaleString("es-CL");
  const carrito = new Map(); // id -> cantidad
  let inicio = null;         // para medir el objetivo de RNF01 (menos de 30 s)

  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
  const tocar = () => { if (!inicio) inicio = Date.now(); };

  // ---- productos ----
  const grilla = $("productos");
  productos.forEach((p) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "btn producto";
    const n = document.createElement("span"); n.textContent = p.nombre;
    const pr = document.createElement("small"); pr.textContent = clp(p.precio);
    b.append(n, pr);
    b.addEventListener("click", () => { tocar(); carrito.set(p.id, (carrito.get(p.id) || 0) + 1); pintar(); });
    grilla.append(b);
  });

  // ---- comanda ----
  function pintar() {
    const ul = $("lineas"); ul.replaceChildren();
    let total = 0;
    if (!carrito.size) { const li = document.createElement("li"); li.className = "suave"; li.textContent = "Aún no hay productos."; ul.append(li); }
    carrito.forEach((cant, id) => {
      const p = productos.find((x) => x.id === id); total += p.precio * cant;
      const li = document.createElement("li");
      const nom = document.createElement("span"); nom.textContent = `${p.nombre}`;
      const ctl = document.createElement("span"); ctl.className = "ctl";
      const menos = btn("−", `Quitar uno de ${p.nombre}`, () => { cant > 1 ? carrito.set(id, cant - 1) : carrito.delete(id); pintar(); });
      const q = document.createElement("b"); q.textContent = cant;
      const mas = btn("+", `Agregar uno de ${p.nombre}`, () => { carrito.set(id, cant + 1); pintar(); });
      ctl.append(menos, q, mas);
      const sub = document.createElement("span"); sub.className = "num"; sub.textContent = clp(p.precio * cant);
      li.append(nom, ctl, sub); ul.append(li);
    });
    $("total").textContent = clp(total);
    validar();
  }
  function btn(txt, aria, fn) {
    const b = document.createElement("button"); b.type = "button"; b.className = "btn mini"; b.textContent = txt;
    b.setAttribute("aria-label", aria); b.addEventListener("click", fn); return b;
  }

  // ---- nombre de quien retira ----
  $("f-retiro").addEventListener("input", () => { tocar(); validar(); });
  $("f-obs").addEventListener("input", validar);

  function faltante() {
    if (!$("f-retiro").value.trim()) return "Escribe el nombre de quien retira.";
    if (!carrito.size) return "Agrega al menos un producto.";
    return "";
  }
  function validar() {
    const f = faltante();
    $("enviar").disabled = !!f;
    $("motivo").textContent = f || "Listo para enviar.";
  }

  // ---- enviar ----
  $("enviar").addEventListener("click", async () => {
    const err = $("error"); err.hidden = true;
    $("enviar").disabled = true;
    try {
      const r = await fetch("/api/pedidos/", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ canal: "retiro", datos: { nombre: $("f-retiro").value }, observaciones: $("f-obs").value, items: [...carrito].map(([producto, cantidad]) => ({ producto, cantidad })) }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "No se pudo enviar el pedido.");
      const seg = Math.round((Date.now() - inicio) / 1000);
      $("cronometro").textContent = `Pedido #${d.id} enviado a cocina en ${seg} s` + (seg <= 30 ? "." : " (la meta es 30 s).");
      carrito.clear(); inicio = null;
      $("f-retiro").value = ""; $("f-obs").value = ""; pintar();
    } catch (e) { err.textContent = e.message; err.hidden = false; validar(); }
  });

  // ---- pedidos listos para entregar (aviso al garzón) ----
  async function listos() {
    try {
      const d = await (await fetch("/api/pedidos/listos/")).json();
      const cont = $("listos"); cont.replaceChildren(); cont.hidden = !d.listos.length;
      d.listos.forEach((p) => {
        const s = document.createElement("span"); s.textContent = `Pedido #${p.id} listo · ${p.canal} ${p.ref}`;
        const b = btn("Entregado", `Marcar entregado el pedido ${p.id}`, async () => {
          await fetch(`/api/pedidos/${p.id}/entregar/`, { method: "POST", headers: { "X-CSRFToken": csrf() } }); listos();
        });
        b.className = "btn chico claro"; cont.append(s, b);
      });
    } catch (_) { /* reintenta en el próximo ciclo */ }
  }
  listos(); setInterval(listos, 3000);
  pintar();
})();
