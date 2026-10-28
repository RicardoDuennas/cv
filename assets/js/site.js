// Menú desplegable en pantallas pequeñas, cambio de tema y botón de impresión del CV.
(function () {
  var root = document.documentElement;
  var theme = document.querySelector('.theme-toggle');
  if (theme) {
    theme.setAttribute('aria-pressed', String(root.dataset.theme === 'dark'));
    theme.addEventListener('click', function () {
      var dark = root.dataset.theme !== 'dark';
      if (dark) {
        root.dataset.theme = 'dark';
      } else {
        delete root.dataset.theme;
      }
      theme.setAttribute('aria-pressed', String(dark));
      try {
        localStorage.setItem('theme', dark ? 'dark' : 'light');
      } catch (e) {}
    });
  }

  var toggle = document.querySelector('.menu-toggle');
  var nav = document.getElementById('site-nav');

  function setOpen(open) {
    toggle.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('nav-open', open);
  }

  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      setOpen(toggle.getAttribute('aria-expanded') !== 'true');
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && document.body.classList.contains('nav-open')) {
        setOpen(false);
        toggle.focus();
      }
    });
  }

  // Correo protegido: la dirección llega invertida en data-email y aquí se convierte en enlace.
  var emails = document.querySelectorAll('[data-email]');
  for (var i = 0; i < emails.length; i++) {
    var address = emails[i].getAttribute('data-email').split('').reverse().join('');
    var link = document.createElement('a');
    link.href = 'mailto:' + address;
    link.textContent = address;
    emails[i].replaceWith(link);
  }

  var print = document.querySelector('[data-print]');
  if (print) {
    print.addEventListener('click', function () {
      window.print();
    });
  }
})();
