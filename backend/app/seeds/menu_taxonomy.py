"""Default menu structure every restaurant starts with (PRD §7.1, §7.2). All of it is editable by the owner.

Shape: meal type -> categories -> optional subcategories. A category can belong to several meal types
(e.g. "Starters" is on both the Lunch and Dinner menus), so it is defined once and linked.
"""

# Meal types in display order.
MEAL_TYPES: list[str] = [
    "Breakfast",
    "Brunch",
    "Snacks & Quick Bites",
    "Lunch",
    "Dinner",
    "Desserts & Sweets",
    "Drinks & Beverages",
    "Special Menu",
]

# (category, meal types, subcategories, is_alcoholic)
CATEGORIES: list[tuple[str, list[str], list[str], bool]] = [
    # Breakfast
    ("Indian Breakfast", ["Breakfast"], [], False),
    ("South Indian Breakfast", ["Breakfast"], [], False),
    ("Continental Breakfast", ["Breakfast"], [], False),
    ("Healthy Breakfast", ["Breakfast"], [], False),
    ("Parathas", ["Breakfast"], [], False),
    ("Eggs & Omelettes", ["Breakfast", "Brunch"], [], False),
    ("Cereals", ["Breakfast"], [], False),
    ("Sandwiches & Toast", ["Breakfast"], [], False),
    # Brunch
    ("Brunch Combos", ["Brunch"], [], False),
    ("Pancakes & Waffles", ["Brunch"], [], False),
    ("Sandwiches & Burgers", ["Brunch"], [], False),
    ("Salads", ["Brunch"], [], False),
    ("Bakery & Pastries", ["Brunch"], [], False),
    ("Juices & Smoothies", ["Brunch"], [], False),
    # Snacks
    ("Indian Snacks", ["Snacks & Quick Bites"], [], False),
    ("Street Food", ["Snacks & Quick Bites"], [], False),
    ("Chaat", ["Snacks & Quick Bites"], [], False),
    ("Samosa & Kachori", ["Snacks & Quick Bites"], [], False),
    ("Pakora", ["Snacks & Quick Bites"], [], False),
    ("Fries & Wedges", ["Snacks & Quick Bites"], [], False),
    ("Nachos", ["Snacks & Quick Bites"], [], False),
    ("Spring Rolls", ["Snacks & Quick Bites"], [], False),
    ("Momos", ["Snacks & Quick Bites"], [], False),
    ("Chicken Wings", ["Snacks & Quick Bites"], [], False),
    ("Quick Bites", ["Snacks & Quick Bites"], [], False),
    # Lunch and Dinner
    (
        "Starters",
        ["Lunch", "Dinner"],
        ["Veg Starters", "Non-Veg Starters", "Tandoori Starters", "Soups", "Salads", "Chinese Starters"],
        False,
    ),
    (
        "Main Course",
        ["Lunch", "Dinner"],
        [
            "Veg Main Course",
            "Non-Veg Main Course",
            "Paneer Dishes",
            "Dal & Curries",
            "Chinese Main Course",
            "Continental Main Course",
            "Rice & Biryani",
            "Thali & Combos",
        ],
        False,
    ),
    (
        "Accompaniments",
        ["Lunch", "Dinner"],
        ["Roti", "Naan", "Kulcha", "Paratha", "Rice", "Raita", "Papad", "Pickles and Chutneys"],
        False,
    ),
    # Desserts
    (
        "Desserts",
        ["Desserts & Sweets"],
        ["Indian Sweets", "Cakes", "Pastries", "Ice Cream", "Brownies", "Puddings", "Cheesecakes", "Dessert Combos"],
        False,
    ),
    # Drinks
    (
        "Non-Alcoholic",
        ["Drinks & Beverages"],
        [
            "Soft Drinks",
            "Fresh Juices",
            "Packaged Juices",
            "Milkshakes",
            "Smoothies",
            "Lassi",
            "Buttermilk",
            "Tea",
            "Coffee",
            "Hot Chocolate",
            "Energy Drinks",
            "Mineral Water",
        ],
        False,
    ),
    (
        "Mocktails",
        ["Drinks & Beverages"],
        ["Virgin Mojito", "Fruit Mocktails", "Iced Tea", "Lemonades", "Special Mocktails"],
        False,
    ),
    (
        "Alcoholic",
        ["Drinks & Beverages"],
        [
            "Beer",
            "Wine",
            "Whisky",
            "Vodka",
            "Rum",
            "Gin",
            "Brandy",
            "Tequila",
            "Cocktails",
            "Alcoholic Mojito",
            "Other Spirits",
        ],
        True,  # disabled until the restaurant's licence is approved (PRD §7.2)
    ),
    # Special categories
    ("Chef's Special", ["Special Menu"], [], False),
    ("Today's Special", ["Special Menu"], [], False),
    ("Best Sellers", ["Special Menu"], [], False),
    ("Combos", ["Special Menu"], [], False),
    ("Family Packs", ["Special Menu"], [], False),
    ("Kids Menu", ["Special Menu"], [], False),
    ("Healthy Food", ["Special Menu"], [], False),
    ("Vegan Food", ["Special Menu"], [], False),
    ("Jain Food", ["Special Menu"], [], False),
    ("Gluten-Free Food", ["Special Menu"], [], False),
    ("Seasonal Specials", ["Special Menu"], [], False),
]
