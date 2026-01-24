# Search User Guide

The Price Error Bot includes powerful search functionality to help you quickly find products, alerts, categories, and scan jobs. This guide covers all search features and how to use them effectively.

## Quick Start

### Basic Search
1. Navigate to the **Search Products** tab in the dashboard
2. Type your search query in the search bar (e.g., "iPhone 13")
3. Results appear instantly with relevance ranking
4. Click on any result to view details

### Advanced Search
1. Click the **Filters** button to open advanced options
2. Select stores, price ranges, and other filters
3. Use Boolean operators: `AND`, `OR`, quotes for exact phrases
4. Combine multiple filters for precise results

## Search Syntax

### Basic Queries
```
iphone                    # Find products containing "iphone"
"iPhone 13 Pro"          # Exact phrase search
B08N5WRWNW               # Find by exact SKU/ASIN
```

### Field-Specific Search
```
title:"MacBook Pro"      # Search only in title field
sku:B08*                 # SKU starting with "B08"
store:amazon             # Products from Amazon only
price:500..1000          # Price range (MSRP or baseline)
```

### Advanced Operators
```
iPhone AND Pro           # Both terms must exist
iPhone OR Samsung        # Either term can exist
"iPhone 13" -refurbished # Exclude "refurbished" items
title:iPhone store:amazon # Multiple field filters
```

### Wildcards and Patterns
```
iPhone*                  # Starts with "iPhone"
*Pro*                   # Contains "Pro" anywhere
B08*WRWNW               # SKU pattern matching
```

## Search Features

### Auto-Complete Suggestions
- **Recent Searches**: Your last 10 searches for quick access
- **Popular Terms**: Most searched terms across all users
- **Smart Suggestions**: AI-powered suggestions based on your query
- **SKU Completion**: Auto-complete for partial SKU matches

### Advanced Filters

#### Product Filters
- **Stores**: Multi-select from available retailers
- **Price Range**: Min/Max price with preset ranges
- **Discount**: Minimum discount percentage
- **Stock Status**: In stock, out of stock, or all
- **Has Alerts**: Products with active price alerts
- **Date Added**: When product was first tracked

#### Alert Filters  
- **Date Range**: When alerts were sent
- **Price Range**: Triggered price ranges
- **Discount Range**: Alert discount percentages
- **Rule Types**: Filter by detection rule types
- **Stores**: Store where alert originated

#### Category Filters
- **Enabled Status**: Active, inactive, or all categories
- **Priority Level**: Category priority (1-10)
- **Performance**: High, medium, or low performing
- **Last Scanned**: Recently scanned categories

### Sorting Options

#### Products
- **Relevance** (Default): Best matches first
- **Newest**: Most recently added products
- **Price Low-High**: Cheapest products first  
- **Price High-Low**: Most expensive products first
- **Name A-Z**: Alphabetical by product title
- **Discount**: Highest discount percentage first

#### Alerts
- **Recent**: Newest alerts first (default)
- **Discount**: Highest discount alerts first
- **Price Drop**: Largest price drops first
- **Store**: Grouped by retailer

#### Categories  
- **Priority**: Highest priority categories first
- **Performance**: Best performing categories first
- **Recent**: Most recently scanned first
- **Name**: Alphabetical by category name

### Search Results

#### Result Cards
Each result shows:
- **Store Badge**: Visual store identifier with brand colors
- **Search Score**: Relevance percentage (when applicable)
- **Highlighted Terms**: Search terms highlighted in yellow
- **Key Metrics**: Price, discount, stock status
- **Quick Actions**: View details, visit store, etc.

#### Result Metadata
- **Total Results**: Number of matching items
- **Response Time**: Query execution time in milliseconds
- **Search Type**: Full-text, exact match, or filtered search
- **Cache Status**: Whether results were cached

## Tips for Better Search Results

### Optimize Your Queries

#### DO:
- Use specific product names: "MacBook Pro 13" vs "laptop"
- Include brand names: "Apple iPhone" vs "phone" 
- Use SKUs when available: "B08N5WRWNW" vs "iPhone"
- Combine filters: price range + store + keywords
- Use quotes for exact phrases: "Nintendo Switch Pro"

#### DON'T:
- Search for very common words: "the", "and", "product"
- Use too many unrelated terms: "iPhone Samsung Dell Microsoft"
- Include stop words: "a", "an", "the", "is", "are"
- Make queries too long (500+ characters)
- Use special SQL characters: %; DROP TABLE

### Filter Effectively

#### Start Broad, Then Narrow
1. Begin with a general search term
2. Review the results and facets
3. Apply filters to narrow down
4. Refine search terms based on results

#### Use Multiple Filter Types
- Combine text search with price ranges
- Filter by store AND stock status
- Use date ranges for time-sensitive searches
- Apply discount filters for deal hunting

#### Save Common Searches
- Bookmark URLs with your filter combinations
- Use recent searches for frequently used queries
- Create filter presets for common scenarios

## Performance Tips

### Fast Searches
- **SKU searches** are fastest (exact match)
- **Store filters** are very efficient  
- **Price range filters** use optimized indexes
- **Date filters** on recent data are fast

### Slower Searches
- **Full-text search** on very common terms
- **Fuzzy matching** on short queries (< 3 characters)
- **Complex boolean queries** with many terms
- **Searches without any filters** (returns everything)

### Optimize for Speed
- Use specific terms rather than broad ones
- Apply at least one filter (store, price, date)
- Avoid wildcard searches on short terms
- Use exact matches when possible

## Troubleshooting

### No Results Found
**Possible Causes:**
- Search terms too specific
- All applicable filters exclude results
- Typos in search terms
- Product not in database

**Solutions:**
- Try broader search terms
- Remove some filters temporarily
- Check spelling and try variations
- Search by SKU if you have it

### Slow Search Performance  
**Possible Causes:**
- Very broad search terms
- Complex filter combinations
- Large result sets
- Database maintenance in progress

**Solutions:**
- Add more specific search terms
- Apply filters to narrow results
- Use smaller result limits (10-20)
- Try again during off-peak hours

### Search Not Working
**Possible Causes:**
- Database connectivity issues
- Search indexes not created
- Browser JavaScript disabled
- API service temporarily down

**Solutions:**
- Refresh the page and try again
- Check browser console for errors
- Ensure database is running
- Contact administrator if persistent

## Advanced Features

### Saved Searches
- Copy URL to save search with filters
- Browser bookmarks preserve search state
- Share search URLs with team members

### Search Analytics
- View search performance in admin panel
- Monitor popular search terms
- Track search success rates
- Optimize based on usage patterns

### API Access
Advanced users can access search functionality via API:

```bash
# Basic product search
curl "http://localhost:8001/api/search/products?q=iphone&limit=10"

# Filtered search
curl "http://localhost:8001/api/search/products?q=laptop&stores=amazon_us&price_min=500&price_max=1500"

# Get suggestions
curl "http://localhost:8001/api/search/suggestions?q=iPh&entity_type=products"
```

## Search Best Practices

### For Deal Discovery
1. Search for specific product categories: "gaming laptop", "4K TV"
2. Apply discount filters: minimum 30-50% off
3. Filter by preferred stores
4. Sort by discount percentage
5. Enable "In Stock Only" filter

### For Product Management
1. Search by SKU for exact products
2. Use store filters for bulk operations
3. Filter by "Has Alerts" to find monitored products
4. Sort by date added to find recent additions

### For Troubleshooting
1. Search error messages in scan job history
2. Filter by failed scans to identify issues
3. Search by store to find store-specific problems
4. Use date filters to find recent issues

### For Category Management
1. Search category names for similar categories
2. Filter by performance to find best/worst performers
3. Use store filters for store-specific management
4. Sort by priority to focus on important categories

## Keyboard Shortcuts

- **Ctrl+K** (or Cmd+K): Focus search bar
- **Enter**: Execute search
- **Escape**: Clear search/close suggestions
- **↑/↓ Arrow Keys**: Navigate suggestions
- **Tab**: Move between filter fields