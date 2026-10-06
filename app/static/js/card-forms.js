/**
 * Dynamic form field visibility for collectible card types
 * Shows/hides card-type-specific fields based on selection
 */

document.addEventListener('DOMContentLoaded', function() {
    const cardTypeSelect = document.getElementById('card_type_id');

    if (!cardTypeSelect) return;

    // Field groups by card type
    const fieldGroups = {
        // Pokémon card fields
        'pokemon': [
            'pokemon_name',
            'pokemon_hp',
            'pokemon_holo_type',
            'pokemon_first_edition',
            'pokemon_shadowless',
            'pokemon_promo',
            'pokemon_illustrator'
        ],
        // Football/Soccer card fields
        'football': [
            'football_player_name',
            'football_team',
            'football_national_team',
            'football_league',
            'football_season',
            'football_is_rookie',
            'football_is_autograph',
            'football_is_relic',
            'football_is_numbered',
            'football_serial_number'
        ],
        // Cricket card fields (for future use)
        'cricket': [
            'cricket_player_name',
            'cricket_team',
            'cricket_series',
            'cricket_match'
        ]
    };

    /**
     * Find the correct field container (label or div depending on form structure)
     */
    function findFieldContainer(fieldId) {
        const field = document.getElementById(fieldId);
        if (!field) return null;

        // Find parent label or form-group
        let parent = field.closest('.form-group');
        if (!parent) {
            parent = field.closest('label');
        }
        if (!parent) {
            parent = field.parentElement;
        }
        return parent;
    }

    /**
     * Get the card type slug from the selected option
     */
    function getCardTypeSlug(cardTypeId) {
        if (!cardTypeId) return null;

        const selectedOption = cardTypeSelect.querySelector(`option[value="${cardTypeId}"]`);
        if (!selectedOption) return null;

        // Extract slug from option text (e.g., "Pokémon" -> "pokemon")
        // Or from data attribute if available
        const text = selectedOption.textContent.toLowerCase();

        // Map display names to slugs
        const nameToSlug = {
            'pokémon': 'pokemon',
            'pokemon': 'pokemon',
            'football': 'football',
            'soccer': 'football',
            'football / soccer': 'football',
            'cricket': 'cricket',
            'basketball': 'basketball'
        };

        // Try exact match first
        if (nameToSlug[text]) return nameToSlug[text];

        // Try partial match
        for (const [name, slug] of Object.entries(nameToSlug)) {
            if (text.includes(name)) return slug;
        }

        return null;
    }

    /**
     * Show/hide fields based on card type
     */
    function updateFormFieldVisibility() {
        const cardTypeId = cardTypeSelect.value;
        const cardTypeSlug = getCardTypeSlug(cardTypeId);

        // Hide all type-specific fields first
        Object.values(fieldGroups).forEach(fields => {
            fields.forEach(fieldId => {
                const container = findFieldContainer(fieldId);
                if (container) {
                    container.style.display = 'none';
                }
            });
        });

        // Show fields for selected card type
        if (cardTypeSlug && fieldGroups[cardTypeSlug]) {
            fieldGroups[cardTypeSlug].forEach(fieldId => {
                const container = findFieldContainer(fieldId);
                if (container) {
                    container.style.display = 'block';
                }
            });
        }

        // Update grading company validation based on is_graded checkbox
        updateGradingValidation();
    }

    /**
     * Enable/disable grading-related fields based on is_graded checkbox
     */
    function updateGradingValidation() {
        const isGradedCheckbox = document.getElementById('is_graded');
        const gradingCompanySelect = document.getElementById('grading_company');
        const gradeField = document.getElementById('grade');
        const certNumberField = document.getElementById('certification_number');

        if (!isGradedCheckbox) return;

        const isGraded = isGradedCheckbox.checked;

        // Enable/disable grading fields
        if (gradingCompanySelect) gradingCompanySelect.disabled = !isGraded;
        if (gradeField) gradeField.disabled = !isGraded;
        if (certNumberField) certNumberField.disabled = !isGraded;

        // Update required status
        if (isGraded) {
            gradingCompanySelect?.setAttribute('data-was-required', 'true');
            gradeField?.setAttribute('data-was-required', 'true');
            certNumberField?.setAttribute('data-was-required', 'true');
        }
    }

    /**
     * Toggle between card and sports terminology for Football cards
     */
    function updateLabelsForCardType() {
        const cardTypeId = cardTypeSelect.value;
        const cardTypeSlug = getCardTypeSlug(cardTypeId);

        // You can add logic here to update labels dynamically if needed
        // For example, change "Card Number" to "Jersey Number" for sports cards
    }

    // Event listeners
    cardTypeSelect.addEventListener('change', function() {
        updateFormFieldVisibility();
        updateLabelsForCardType();
    });

    // Handle is_graded checkbox
    const isGradedCheckbox = document.getElementById('is_graded');
    if (isGradedCheckbox) {
        isGradedCheckbox.addEventListener('change', updateGradingValidation);
    }

    // Initialize visibility on page load
    updateFormFieldVisibility();
});

/**
 * Validate card form on submission
 */
function validateCardForm() {
    const cardTypeId = document.getElementById('card_type_id').value;
    const cardName = document.getElementById('card_name').value.trim();
    const condition = document.getElementById('condition').value;
    const confirmAccuracy = document.getElementById('confirm_accuracy').checked;

    if (!cardTypeId) {
        alert('Please select a card type');
        return false;
    }

    if (!cardName) {
        alert('Please enter a card name');
        return false;
    }

    if (!condition) {
        alert('Please select a condition');
        return false;
    }

    if (!confirmAccuracy) {
        alert('Please confirm that the information is accurate');
        return false;
    }

    return true;
}
