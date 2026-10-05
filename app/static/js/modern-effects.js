/* Modern UI Effects for ChainBid */

// 1. Cursor Beam Effect
(function() {
  const beam = document.createElement('div');
  beam.className = 'cursor-beam';
  document.body.appendChild(beam);

  document.addEventListener('mousemove', (e) => {
    beam.style.left = (e.clientX - 150) + 'px';
    beam.style.top = (e.clientY - 150) + 'px';
  });
})();

// 2. Scroll Fade-In Animation
function initScrollFadeIn() {
  const sections = document.querySelectorAll('.fade-in-section');

  const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
  };

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, observerOptions);

  sections.forEach(section => {
    observer.observe(section);
  });
}

// 3. Lucide Icons Initialization
function initLucideIcons() {
  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }
}

// 4. Button Hover Effects
function initButtonEffects() {
  const buttons = document.querySelectorAll('.btn-hover-fade');

  buttons.forEach(button => {
    button.addEventListener('mouseenter', function() {
      this.style.opacity = '0.8';
      this.style.transform = 'translateY(-2px)';
    });

    button.addEventListener('mouseleave', function() {
      this.style.opacity = '1';
      this.style.transform = 'translateY(0)';
    });
  });
}

// 5. Card Hover Effects
function initCardEffects() {
  const cards = document.querySelectorAll('.glass-card, .card-colored');

  cards.forEach(card => {
    card.addEventListener('mouseenter', function() {
      this.style.transform = 'translateY(-4px)';
      this.style.boxShadow = '0 20px 40px rgba(0, 0, 0, 0.1)';
    });

    card.addEventListener('mouseleave', function() {
      this.style.transform = 'translateY(0)';
      this.style.boxShadow = '0 0 0 1px rgba(0, 0, 0, 0.1)';
    });
  });
}

// 6. Gradient Text Animation
function initGradientText() {
  const gradientTexts = document.querySelectorAll('.hero-gradient');

  gradientTexts.forEach(text => {
    text.style.backgroundSize = '200% 200%';
    text.style.animation = 'gradientShift 8s ease infinite';
  });
}

// 7. Icon Box Effects
function initIconBoxes() {
  const boxes = document.querySelectorAll('.icon-box');

  boxes.forEach(box => {
    box.addEventListener('mouseenter', function() {
      this.style.transform = 'translateY(-8px)';
    });

    box.addEventListener('mouseleave', function() {
      this.style.transform = 'translateY(0)';
    });
  });
}

// 8. Initialize All Effects
document.addEventListener('DOMContentLoaded', function() {
  initScrollFadeIn();
  initLucideIcons();
  initButtonEffects();
  initCardEffects();
  initGradientText();
  initIconBoxes();
});

// 9. Reinitialize Lucide Icons after AJAX/DOM updates
const originalFetch = window.fetch;
window.fetch = function(...args) {
  return originalFetch.apply(this, args).then(response => {
    response.clone().text().then(() => {
      setTimeout(initLucideIcons, 100);
    });
    return response;
  });
};

// 10. Dark Mode Detection
function detectDarkMode() {
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    document.documentElement.setAttribute('data-theme', 'dark');
  } else {
    document.documentElement.setAttribute('data-theme', 'light');
  }
}

window.addEventListener('load', detectDarkMode);
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', detectDarkMode);
