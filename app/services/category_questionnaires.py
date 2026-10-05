"""Category-specific questionnaires for detailed product information."""

# Category ID mapping (based on default categories)
CATEGORY_ELECTRONICS = 1
CATEGORY_FASHION = 2
CATEGORY_HOME_GARDEN = 3
CATEGORY_COLLECTIBLES = 4
CATEGORY_BOOKS = 5
CATEGORY_SPORTS = 6

QUESTIONNAIRES = {
    CATEGORY_ELECTRONICS: {
        "name": "Electronics",
        "fields": [
            {
                "name": "brand",
                "label": "Brand",
                "type": "text",
                "placeholder": "e.g., Apple, Samsung, Dell",
                "required": False,
            },
            {
                "name": "model",
                "label": "Model",
                "type": "text",
                "placeholder": "e.g., iPhone 14 Pro, Galaxy S23",
                "required": False,
            },
            {
                "name": "color",
                "label": "Color",
                "type": "text",
                "placeholder": "e.g., Silver, Space Gray, Black",
                "required": False,
            },
            {
                "name": "condition",
                "label": "Condition",
                "type": "select",
                "options": ["New", "Like New", "Good", "Fair", "Poor"],
                "required": True,
            },
            {
                "name": "processor",
                "label": "Processor/CPU",
                "type": "text",
                "placeholder": "e.g., Intel i7, Apple M2, Snapdragon 8 Gen 2",
                "required": False,
            },
            {
                "name": "ram",
                "label": "RAM Memory",
                "type": "text",
                "placeholder": "e.g., 8GB, 16GB, 32GB",
                "required": False,
            },
            {
                "name": "storage",
                "label": "Storage",
                "type": "text",
                "placeholder": "e.g., 256GB SSD, 512GB NVMe, 1TB HDD",
                "required": False,
            },
            {
                "name": "screen_size",
                "label": "Screen Size",
                "type": "text",
                "placeholder": "e.g., 6.1 inches, 15.6 inches, 5 inches",
                "required": False,
            },
            {
                "name": "battery",
                "label": "Battery Status",
                "type": "text",
                "placeholder": "e.g., Excellent, Good, Fair, Needs replacement",
                "required": False,
            },
            {
                "name": "warranty",
                "label": "Warranty",
                "type": "text",
                "placeholder": "e.g., 1 year, 6 months, No warranty",
                "required": False,
            },
            {
                "name": "shipping_info",
                "label": "Shipping Notes",
                "type": "textarea",
                "placeholder": "Any special shipping considerations",
                "required": False,
            },
        ],
    },
    CATEGORY_FASHION: {
        "name": "Fashion",
        "fields": [
            {
                "name": "designer",
                "label": "Designer/Brand",
                "type": "text",
                "placeholder": "e.g., Gucci, Nike, Zara",
                "required": False,
            },
            {
                "name": "size",
                "label": "Size",
                "type": "text",
                "placeholder": "e.g., Small, Medium, Large, 10, EU 42",
                "required": True,
            },
            {
                "name": "color",
                "label": "Color",
                "type": "text",
                "placeholder": "e.g., Navy Blue, Black, White",
                "required": False,
            },
            {
                "name": "fabric",
                "label": "Fabric/Material",
                "type": "text",
                "placeholder": "e.g., 100% Cotton, Silk, Polyester blend",
                "required": False,
            },
            {
                "name": "fit",
                "label": "Fit",
                "type": "text",
                "placeholder": "e.g., Regular fit, Slim fit, Oversized",
                "required": False,
            },
            {
                "name": "condition",
                "label": "Condition",
                "type": "select",
                "options": ["New", "Like New", "Good", "Fair", "Poor"],
                "required": True,
            },
            {
                "name": "care_instructions",
                "label": "Care Instructions",
                "type": "textarea",
                "placeholder": "e.g., Dry clean only, Machine wash cold",
                "required": False,
            },
        ],
    },
    CATEGORY_HOME_GARDEN: {
        "name": "Home & Garden",
        "fields": [
            {
                "name": "furniture_type",
                "label": "Item Type",
                "type": "text",
                "placeholder": "e.g., Sofa, Dining Table, Bookshelf",
                "required": True,
            },
            {
                "name": "material_home",
                "label": "Material",
                "type": "text",
                "placeholder": "e.g., Wood, Metal, Glass, Leather",
                "required": False,
            },
            {
                "name": "color",
                "label": "Color",
                "type": "text",
                "placeholder": "e.g., Oak, Black, White, Brown",
                "required": False,
            },
            {
                "name": "dimensions_home",
                "label": "Dimensions (LxWxH)",
                "type": "text",
                "placeholder": "e.g., 200cm x 100cm x 80cm",
                "required": False,
            },
            {
                "name": "condition",
                "label": "Condition",
                "type": "select",
                "options": ["Like New", "Good", "Fair", "Poor"],
                "required": True,
            },
            {
                "name": "assembly_required",
                "label": "Assembly Required?",
                "type": "checkbox",
                "required": False,
            },
            {
                "name": "shipping_weight",
                "label": "Weight",
                "type": "text",
                "placeholder": "e.g., 50kg, 25kg",
                "required": False,
            },
        ],
    },
    CATEGORY_COLLECTIBLES: {
        "name": "Collectibles",
        "fields": [
            {
                "name": "artist_name",
                "label": "Artist/Creator",
                "type": "text",
                "placeholder": "Name of artist or creator",
                "required": False,
            },
            {
                "name": "edition",
                "label": "Edition",
                "type": "text",
                "placeholder": "e.g., Limited Edition 1/1000, First Edition",
                "required": False,
            },
            {
                "name": "rarity",
                "label": "Rarity Level",
                "type": "select",
                "options": ["Common", "Uncommon", "Rare", "Very Rare", "Ultra Rare", "Unique"],
                "required": False,
            },
            {
                "name": "authentication",
                "label": "Authentication",
                "type": "text",
                "placeholder": "e.g., Certificate of Authenticity, Certified by PSA",
                "required": False,
            },
            {
                "name": "condition",
                "label": "Condition",
                "type": "select",
                "options": ["Mint", "Near Mint", "Excellent", "Very Good", "Good", "Fair", "Poor"],
                "required": True,
            },
            {
                "name": "provenance",
                "label": "Provenance/History",
                "type": "textarea",
                "placeholder": "History and origin of the item",
                "required": False,
            },
            {
                "name": "storage_info",
                "label": "Storage Conditions",
                "type": "textarea",
                "placeholder": "How has it been stored",
                "required": False,
            },
        ],
    },
    CATEGORY_BOOKS: {
        "name": "Books",
        "fields": [
            {
                "name": "author",
                "label": "Author",
                "type": "text",
                "placeholder": "Author name",
                "required": False,
            },
            {
                "name": "isbn",
                "label": "ISBN",
                "type": "text",
                "placeholder": "e.g., 978-0-06-112008-4",
                "required": False,
            },
            {
                "name": "publisher",
                "label": "Publisher",
                "type": "text",
                "placeholder": "Publisher name",
                "required": False,
            },
            {
                "name": "publication_year",
                "label": "Publication Year",
                "type": "number",
                "placeholder": "e.g., 2023",
                "required": False,
            },
            {
                "name": "binding",
                "label": "Binding Type",
                "type": "select",
                "options": ["Hardcover", "Paperback", "Leather Bound", "Other"],
                "required": False,
            },
            {
                "name": "pages",
                "label": "Number of Pages",
                "type": "number",
                "placeholder": "e.g., 320",
                "required": False,
            },
            {
                "name": "language",
                "label": "Language",
                "type": "text",
                "placeholder": "e.g., English, Spanish, French",
                "required": False,
            },
            {
                "name": "condition",
                "label": "Condition",
                "type": "select",
                "options": ["Like New", "Fine", "Very Good", "Good", "Fair", "Poor"],
                "required": True,
            },
            {
                "name": "edition",
                "label": "Edition",
                "type": "text",
                "placeholder": "e.g., First Edition, 2nd Edition",
                "required": False,
            },
        ],
    },
    CATEGORY_SPORTS: {
        "name": "Sports",
        "fields": [
            {
                "name": "sport_type",
                "label": "Sport Type",
                "type": "text",
                "placeholder": "e.g., Football, Basketball, Tennis, Cycling",
                "required": True,
            },
            {
                "name": "sport_brand",
                "label": "Brand",
                "type": "text",
                "placeholder": "e.g., Nike, Adidas, Wilson, Specialized",
                "required": False,
            },
            {
                "name": "size_sport",
                "label": "Size",
                "type": "text",
                "placeholder": "e.g., Size 10, Medium, Large, 56cm",
                "required": False,
            },
            {
                "name": "material_sport",
                "label": "Material",
                "type": "text",
                "placeholder": "e.g., Leather, Carbon Fiber, Rubber",
                "required": False,
            },
            {
                "name": "color",
                "label": "Color",
                "type": "text",
                "placeholder": "e.g., Black, White, Red",
                "required": False,
            },
            {
                "name": "condition",
                "label": "Condition",
                "type": "select",
                "options": ["New", "Like New", "Good", "Fair", "Poor"],
                "required": True,
            },
            {
                "name": "warranty",
                "label": "Warranty/Guarantee",
                "type": "text",
                "placeholder": "Any warranty or guarantee",
                "required": False,
            },
        ],
    },
}


def get_questionnaire(category_id):
    """Get the questionnaire for a category."""
    return QUESTIONNAIRES.get(category_id, {})


def get_all_questionnaires():
    """Get all questionnaires."""
    return QUESTIONNAIRES


def get_category_questions(category_id):
    """Get just the questions/fields for a category."""
    questionnaire = QUESTIONNAIRES.get(category_id, {})
    return questionnaire.get("fields", [])
