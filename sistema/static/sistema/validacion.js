/* Campos numéricos: quita letras y símbolos mientras se escribe o se pega.
   Uso en HTML: data-tipo="entero" (dinero y mesa), "decimal" (cantidades) o "telefono".
   El servidor vuelve a validar todo, esto es solo ayuda visual. */
(() => {
  const REGLAS = {
    entero: { limpiar: (v) => v.replace(/\D/g, ""), msg: "Solo números, sin letras ni símbolos." },
    decimal: {
      limpiar: (v) => {
        v = v.replace(/[^\d.,]/g, "");
        const i = v.search(/[.,]/);
        return i < 0 ? v : v.slice(0, i + 1) + v.slice(i + 1).replace(/[.,]/g, "");
      },
      msg: "Solo números; para decimales usa una coma.",
    },
    telefono: { limpiar: (v) => v.replace(/[^\d+\s-]/g, ""), msg: "Solo números, espacios, + y -." },
  };

  function avisar(el, texto) {
    let a = el.parentElement.querySelector(".aviso-campo");
    if (!a) {
      a = document.createElement("small");
      a.className = "aviso-campo"; a.setAttribute("role", "status");
      el.insertAdjacentElement("afterend", a);
    }
    a.textContent = texto; el.classList.add("invalido");
    clearTimeout(a._t);
    a._t = setTimeout(() => { a.remove(); el.classList.remove("invalido"); }, 2500);
  }

  // Fase de captura: corrige el valor antes de que otros scripts (como el total del pedido) lo lean.
  document.addEventListener("input", (e) => {
    const el = e.target, regla = el.dataset && REGLAS[el.dataset.tipo];
    if (!regla) return;
    const limpio = regla.limpiar(el.value);
    if (limpio !== el.value) { el.value = limpio; avisar(el, regla.msg); }
  }, true);

  // Un campo de costo no puede quedar vacío al salir de él: se deja en 0.
  document.addEventListener("blur", (e) => {
    const el = e.target;
    if (el.dataset && el.dataset.tipo === "entero" && el.dataset.cero !== undefined && el.value === "") {
      el.value = "0"; el.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }, true);
})();
