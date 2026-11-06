/* Report download, made in the browser (DECISIONS D42). One delegated listener; safe to load many times.
   Why not st.download_button: it serves the file from one server instance's memory, and on Vercel the
   follow-up request can reach another instance ("file not available on site"). */
(function () {
  if (window.__moatDl) return;
  window.__moatDl = true;
  document.addEventListener("click", function (e) {
    var b = e.target.closest(".rp-dl");
    if (!b) return;
    var bin = atob(b.dataset.b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    var url = URL.createObjectURL(new Blob([bytes], { type: "text/markdown;charset=utf-8" }));
    var a = document.createElement("a");
    a.href = url;
    a.download = b.dataset.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    b.dataset.state = "done"; // swaps the label to "Saved" for a moment (CSS)
    setTimeout(function () { delete b.dataset.state; }, 1600);
  });
})();
