/* Gráficos del reporte: torta y barras en SVG puro (sin librerías externas).
   Los datos llegan con json_script y todo texto se inserta con textContent. */
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const COLORES = ["#b3302a", "#c98a00", "#2f6b3a", "#2b6cb0", "#7b4a9e", "#4a5568", "#d9622b", "#1f8a8a"];
  const clp = (n) => "$" + Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const el = (nombre, attrs = {}, texto) => {
    const e = document.createElementNS(NS, nombre);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (texto !== undefined) e.textContent = texto;
    return e;
  };
  const html = (nombre, clase, texto) => {
    const e = document.createElement(nombre);
    if (clase) e.className = clase;
    if (texto !== undefined) e.textContent = texto;
    return e;
  };
  const leer = (id) => {
    try { return JSON.parse(document.getElementById(id).textContent) || []; } catch (e) { return []; }
  };

  function torta(cont, datos) {
    const total = datos.reduce((a, d) => a + d.valor, 0);
    const R = 90, C = 100;
    const svg = el("svg", { viewBox: "0 0 200 200", class: "torta", role: "img",
      "aria-label": "Gráfico de torta: " + datos.map((d) => d.etiqueta).join(", ") });
    if (datos.length === 1) {
      svg.appendChild(el("circle", { cx: C, cy: C, r: R, fill: COLORES[0] }));
    } else {
      let ang = -Math.PI / 2;
      datos.forEach((d, i) => {
        const frac = d.valor / total, fin = ang + frac * 2 * Math.PI;
        const x1 = C + R * Math.cos(ang), y1 = C + R * Math.sin(ang);
        const x2 = C + R * Math.cos(fin), y2 = C + R * Math.sin(fin);
        const p = el("path", { d: `M${C},${C} L${x1},${y1} A${R},${R} 0 ${frac > 0.5 ? 1 : 0} 1 ${x2},${y2} Z`,
          fill: COLORES[i % COLORES.length], class: "trozo" });
        p.appendChild(el("title", {}, `${d.etiqueta}: ${clp(d.valor)} (${Math.round(frac * 100)}%)`));
        svg.appendChild(p);
        ang = fin;
      });
    }
    const leyenda = html("ul", "leyenda");
    datos.forEach((d, i) => {
      const li = html("li");
      const mu = html("span", "muestra"); mu.style.background = COLORES[i % COLORES.length];
      const txt = html("span", "", d.etiqueta);
      const pct = Math.round((d.valor / total) * 100);
      const num = html("span", "num", `${clp(d.valor)} · ${pct}%`);
      li.append(mu, txt, num);
      if (d.extra !== undefined) {
        const sub = html("small", "suave", `${d.extra} ${cont.dataset.extra || ""}${d.extra === 1 ? "" : "s"}`);
        txt.append(" ", sub);
      }
      leyenda.appendChild(li);
    });
    cont.append(svg, leyenda);
  }

  function barras(cont, datos) {
    const max = Math.max(...datos.map((d) => d.valor)) || 1;
    const fila = 36, izq = 170, ancho = 400, alto = datos.length * fila + 6;
    const svg = el("svg", { viewBox: `0 0 ${izq + ancho + 40} ${alto}`, class: "barras", role: "img",
      "aria-label": "Gráfico de barras de los productos más vendidos" });
    datos.forEach((d, i) => {
      const y = i * fila + 4, w = Math.max(3, (d.valor / max) * ancho);
      const nombre = d.etiqueta.length > 22 ? d.etiqueta.slice(0, 21) + "…" : d.etiqueta;
      const t = el("text", { x: izq - 8, y: y + 18, "text-anchor": "end", class: "eje" }, nombre);
      t.appendChild(el("title", {}, d.etiqueta));
      svg.appendChild(t);
      const r = el("rect", { x: izq, y, width: w, height: 24, rx: 4, fill: COLORES[i % COLORES.length] });
      r.appendChild(el("title", {}, `${d.etiqueta}: ${d.valor} ${cont.dataset.unidad || ""}`));
      svg.appendChild(r);
      svg.appendChild(el("text", { x: izq + w + 6, y: y + 18, class: "valor" }, String(d.valor)));
    });
    cont.appendChild(svg);
  }

  document.querySelectorAll(".grafico").forEach((cont) => {
    const datos = leer(cont.dataset.fuente).filter((d) => d.valor > 0);
    if (!datos.length) { cont.appendChild(html("p", "vacio", cont.dataset.vacio || "Sin datos.")); return; }
    (cont.dataset.tipo === "barras" ? barras : torta)(cont, datos);
  });
})();
