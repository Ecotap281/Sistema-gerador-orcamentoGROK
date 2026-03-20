// /Sistema-gerador-orcamentoGROK-main/static/ui.js
(() => {
  const ta = document.getElementById("texto");
  const btnClear = document.getElementById("btn-clear");

  if (btnClear && ta) {
    btnClear.addEventListener("click", () => {
      ta.value = "";
      ta.focus();
    });
  }

  if (ta) {
    const autosize = () => {
      ta.style.height = "auto";
      ta.style.height = Math.min(720, ta.scrollHeight + 2) + "px";
    };
    ta.addEventListener("input", autosize);
    window.addEventListener("load", autosize);
  }
})();
