// Renders a small 3D bar chart of the user's actual positions (from Alpaca).
// Bar heights are driven entirely by data passed in — nothing here invents
// numbers. If there are no positions, it renders an empty baseline.
function renderPortfolio3D(canvasId, positions) {
  if (typeof THREE === "undefined") return;
  var mount = document.getElementById(canvasId);
  if (!mount) return;

  var width = mount.clientWidth || 600;
  var height = mount.clientHeight || 320;

  var renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(width, height);
  mount.innerHTML = "";
  mount.appendChild(renderer.domElement);

  var scene = new THREE.Scene();
  var camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
  camera.position.set(0, 4, 9);
  camera.lookAt(0, 0, 0);

  scene.add(new THREE.PointLight(0xd4af6a, 1.8, 40)).position.set(4, 6, 4);
  scene.add(new THREE.AmbientLight(0x334, 1.2));

  var values = (positions || []).map(function (p) {
    return Math.abs(parseFloat(p.market_value || 0));
  });
  var max = Math.max.apply(null, values.concat([1]));

  var group = new THREE.Group();
  var n = Math.max(positions.length, 1);
  var spacing = 1.4;
  var startX = -((n - 1) * spacing) / 2;

  (positions.length ? positions : [{ symbol: "—", market_value: 0 }]).forEach(function (p, i) {
    var val = Math.abs(parseFloat(p.market_value || 0));
    var h = 0.15 + (val / max) * 3.2;
    var geo = new THREE.BoxGeometry(0.7, h, 0.7);
    var mat = new THREE.MeshStandardMaterial({
      color: parseFloat(p.unrealized_pl || 0) >= 0 ? 0x4c9a73 : 0xc06a52,
      metalness: 0.25,
      roughness: 0.5,
    });
    var mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(startX + i * spacing, h / 2 - 1.2, 0);
    group.add(mesh);

    var edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: 0xd4af6a, transparent: true, opacity: 0.5 })
    );
    edges.position.copy(mesh.position);
    group.add(edges);
  });

  scene.add(group);

  function resize() {
    var w = mount.clientWidth, h = mount.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }
  window.addEventListener("resize", resize);

  function animate() {
    requestAnimationFrame(animate);
    group.rotation.y += 0.003;
    renderer.render(scene, camera);
  }
  animate();
}
