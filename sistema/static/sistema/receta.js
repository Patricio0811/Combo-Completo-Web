/* Agrega filas a la receta del producto clonando la fila vacía del formset de Django. */
(() => {
  const boton = document.getElementById("mas-insumos");
  if (!boton) return;
  boton.addEventListener("click", () => {
    const total = document.getElementById("id_recetas-TOTAL_FORMS");
    const n = Number(total.value);
    const html = document.getElementById("fila-vacia").innerHTML.replaceAll("__prefix__", n);
    document.getElementById("filas-receta").insertAdjacentHTML("beforeend", html);
    total.value = n + 1;
  });
})();
