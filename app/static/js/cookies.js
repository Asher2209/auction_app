// Cookie consent management
(function() {
  const COOKIE_CONSENT_KEY = 'chainbid_cookie_consent';
  const COOKIE_PREFERENCES_KEY = 'chainbid_cookie_preferences';

  // Initialize cookie banner on page load
  document.addEventListener('DOMContentLoaded', function() {
    const consent = getCookieConsent();
    const banner = document.getElementById('cookie-banner');

    if (!consent) {
      // Show banner if no consent given yet
      if (banner) banner.style.display = 'block';
    } else {
      // Hide banner if consent already given
      if (banner) banner.style.display = 'none';
    }

    // Setup event listeners
    const acceptBtn = document.getElementById('cookie-accept');
    const rejectBtn = document.getElementById('cookie-reject');
    const preferencesBtn = document.getElementById('cookie-preferences');
    const saveBtn = document.getElementById('cookie-save');

    if (acceptBtn) {
      acceptBtn.addEventListener('click', function() {
        setCookieConsent({
          essential: true,
          preferences: true,
          analytics: true,
          marketing: true
        });
        hideBanner();
      });
    }

    if (rejectBtn) {
      rejectBtn.addEventListener('click', function() {
        setCookieConsent({
          essential: true,
          preferences: false,
          analytics: false,
          marketing: false
        });
        hideBanner();
      });
    }

    if (preferencesBtn) {
      preferencesBtn.addEventListener('click', function() {
        const modal = new bootstrap.Modal(document.getElementById('cookie-modal'));
        modal.show();
      });
    }

    if (saveBtn) {
      saveBtn.addEventListener('click', function() {
        const preferences = {
          essential: true, // always true
          preferences: document.getElementById('cookie-preferences').checked,
          analytics: document.getElementById('cookie-analytics').checked,
          marketing: document.getElementById('cookie-marketing').checked
        };
        setCookieConsent(preferences);
        hideBanner();
        const modal = bootstrap.Modal.getInstance(document.getElementById('cookie-modal'));
        if (modal) modal.hide();
      });
    }
  });

  // Get cookie consent from localStorage
  function getCookieConsent() {
    const consent = localStorage.getItem(COOKIE_CONSENT_KEY);
    return consent ? JSON.parse(consent) : null;
  }

  // Set cookie consent in localStorage
  function setCookieConsent(preferences) {
    const expiryDate = new Date();
    expiryDate.setFullYear(expiryDate.getFullYear() + 1);

    const consentData = {
      ...preferences,
      timestamp: new Date().toISOString(),
      expiry: expiryDate.toISOString()
    };

    localStorage.setItem(COOKIE_CONSENT_KEY, JSON.stringify(consentData));
    localStorage.setItem(COOKIE_PREFERENCES_KEY, JSON.stringify(preferences));

    // Apply preferences
    applyPreferences(preferences);
  }

  // Hide cookie banner
  function hideBanner() {
    const banner = document.getElementById('cookie-banner');
    if (banner) {
      banner.style.display = 'none';
    }
  }

  // Apply cookie preferences (enable/disable tracking, etc.)
  function applyPreferences(preferences) {
    // Essential cookies are always set by the server (session, csrf_token)

    if (preferences.analytics) {
      // Enable analytics tracking (Google Analytics would go here)
      console.log('Analytics cookies enabled');
    }

    if (preferences.preferences) {
      // Enable preference cookies
      console.log('Preference cookies enabled');
    }

    if (preferences.marketing) {
      // Enable marketing cookies
      console.log('Marketing cookies enabled');
    }
  }

  // Expose functions globally for testing/access
  window.CookieConsent = {
    getCookieConsent: getCookieConsent,
    setCookieConsent: setCookieConsent,
    resetConsent: function() {
      localStorage.removeItem(COOKIE_CONSENT_KEY);
      localStorage.removeItem(COOKIE_PREFERENCES_KEY);
      location.reload();
    }
  };
})();
