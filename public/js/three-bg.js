// Reusable scroll/idle-driven flythrough background.
// Usage: <canvas id="scene-canvas"></canvas> + <script src="/js/three-bg.js"></script>
(function () {
  function init() {
    if (typeof THREE === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    var canvas = document.getElementById("scene-canvas");
    if (!canvas) return;

    var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);

    var scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x0a111d, 0.022);

    var camera = new THREE.PerspectiveCamera(52, window.innerWidth / window.innerHeight, 0.1, 260);
    camera.position.set(0, 1.4, 10);

    scene.add(new THREE.PointLight(0xd4af6a, 2.0, 80)).position.set(8, 12, 6);
    scene.add(new THREE.PointLight(0x2c4a5e, 1.2, 80)).position.set(-10, -6, -10);
    scene.add(new THREE.AmbientLight(0x1c2430, 1.1));

    var matBlock = new THREE.MeshStandardMaterial({ color: 0x101c2c, metalness: 0.3, roughness: 0.55 });
    var edgeMat = new THREE.LineBasicMaterial({ color: 0xb98f4a, transparent: true, opacity: 0.55 });
    var edgeMatFaint = new THREE.LineBasicMaterial({ color: 0x4c7a9a, transparent: true, opacity: 0.35 });

    var group = new THREE.Group();
    scene.add(group);

    var ROWS = 22, DEPTH = 130;
    for (var i = 0; i < ROWS; i++) {
      var z = -(i / ROWS) * DEPTH - Math.random() * 2;
      [-1, 1].forEach(function (side) {
        var count = 2 + Math.floor(Math.random() * 2);
        for (var k = 0; k < count; k++) {
          var h = 0.8 + Math.random() * 4.2;
          var w = 0.5 + Math.random() * 0.6;
          var geo = new THREE.BoxGeometry(w, h, w);
          var mesh = new THREE.Mesh(geo, matBlock);
          mesh.position.set(side * (3.2 + Math.random() * 4 + k * 0.9), h / 2 - 1.6, z - k * 0.6);
          group.add(mesh);
          var line = new THREE.LineSegments(new THREE.EdgesGeometry(geo), Math.random() > 0.6 ? edgeMat : edgeMatFaint);
          line.position.copy(mesh.position);
          group.add(line);
        }
      });
    }

    window.addEventListener("resize", function () {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    });

    var scrollFrac = 0;
    function updateScroll() {
      var doc = document.documentElement;
      var max = doc.scrollHeight - doc.clientHeight;
      scrollFrac = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
    }
    window.addEventListener("scroll", updateScroll, { passive: true });
    updateScroll();

    var t = 0;
    function animate() {
      requestAnimationFrame(animate);
      t += 0.002;
      // On short pages (login/signup) there's little to scroll, so blend a
      // slow idle drift with whatever scroll progress exists.
      var driftFrac = (Math.sin(t) + 1) / 2 * 0.15;
      var frac = Math.min(1, scrollFrac + driftFrac);
      var targetZ = 10 - frac * (DEPTH + 8);
      camera.position.z += (targetZ - camera.position.z) * 0.05;
      camera.position.x = Math.sin(frac * Math.PI * 1.6) * 0.5;
      camera.lookAt(0, 0.4, camera.position.z - 12);
      renderer.render(scene, camera);
    }
    animate();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
