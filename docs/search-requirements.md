# Search Requirements & UX Specification

## User Experience Goals

### Primary Search Interface
- **Global Search Bar**: Single search input at top of dashboard
- **Instant Results**: Debounced search with 300ms delay
- **Multi-Entity Search**: Search across products, alerts, categories, scan jobs
- **Typeahead Suggestions**: Auto-complete for common terms and identifiers

### Search Capabilities

#### Multi-Field Matching
Search should match across these fields with appropriate weighting:

**Products (Weight: High → Low)**
1. **SKU/ASIN/UPC** (Exact match, highest priority)
2. **Title** (Full-text search with stemming)
3. **Brand** (Exact and partial match)
4. **Store** (Exact match)
5. **Category** (Derived from URL or manual tagging)
6. **Internal ID** (Exact match for direct access)

**Alerts (Weight: High → Low)**
1. **Product Title** (via product relationship)
2. **Product SKU** (via product relationship)
3. **Store** (via product relationship)
4. **Triggered Price Range**
5. **Discord Message ID**

**Categories (Weight: High → Low)**
1. **Category Name** (Full-text search)
2. **Store** (Exact match)
3. **Keywords** (JSON array search)
4. **Category URL** (Partial match)

**Scan Jobs (Weight: High → Low)**
1. **Job Type** (Exact match)
2. **Status** (Exact match)
3. **Error Message** (Full-text search)
4. **Store** (via category relationship)

#### Advanced Filters
Users should be able to combine search with these filters:

**Global Filters**
- **Store**: Multi-select dropdown (Amazon, Walmart, Best Buy, etc.)
- **Date Range**: From/To date picker with presets (Today, Week, Month, Year)
- **Active Only**: Toggle to show only active/enabled items

**Product-Specific Filters**
- **Price Range**: Min/Max slider with preset ranges
- **Has Alerts**: Boolean toggle
- **In Stock**: Boolean based on latest price history
- **MSRP Range**: Min/Max for MSRP values
- **Created Date**: Date range for when product was added

**Alert-Specific Filters**
- **Discount %**: Min/Max percentage slider
- **Price Drop Amount**: Min/Max dollar amount
- **Rule Type**: Multi-select for different rule types
- **Sent Date**: Date range for when alert was sent

**Category-Specific Filters**
- **Enabled Status**: Active/Inactive/All
- **Priority Level**: 1-10 range slider
- **Performance**: High/Medium/Low based on deals_found ratio
- **Last Scan**: Date range for last_scanned timestamp

**Scan Job-Specific Filters**
- **Status**: Multi-select (Pending, Running, Completed, Failed)
- **Job Type**: Multi-select (Category, Manual, Scheduled)
- **Success Rate**: Percentage range
- **Duration**: Min/Max execution time

#### Sorting Options
Results should be sortable by:

1. **Relevance** (Default) - Calculated search score
2. **Newest** - Most recently created/modified
3. **Price Ascending** - Lowest to highest price
4. **Price Descending** - Highest to lowest price  
5. **Discount Descending** - Highest discount percentage first
6. **Name/Title** - Alphabetical order
7. **Store** - Grouped by store, then by relevance

#### Pagination Strategy
- **Cursor-based pagination** for stability during real-time updates
- **20 items per page** default (configurable 10/20/50/100)
- **Infinite scroll** option for power users
- **Jump to page** for large result sets
- **Results counter**: "Showing 1-20 of 1,247 results"

### Search Query Syntax

#### Basic Search
```
iphone          # Simple text search
"iphone 12"     # Exact phrase search
SKU:B08N5WRWNW  # Field-specific search
store:amazon    # Store-specific search
```

#### Advanced Search
```
iphone AND (deal OR discount)     # Boolean operators
price:100..500                    # Range queries
created:2023-01-01..2023-12-31   # Date ranges
-refurbished                     # Exclude terms
title:"MacBook Pro" store:amazon # Multiple fields
```

#### Search Shortcuts
```
#electronics    # Search within category
@amazon         # Search within store
$100-500       # Price range shortcut
%50+           # Discount percentage
!failed        # Status/boolean shortcuts
```

### User Interface Components

#### Global Search Bar
```html
<div class="search-container">
  <input 
    type="text" 
    placeholder="Search products, alerts, categories..."
    class="search-input"
  >
  <div class="search-scope">
    <select>
      <option value="all">All</option>
      <option value="products">Products</option>
      <option value="alerts">Alerts</option>
      <option value="categories">Categories</option>
    </select>
  </div>
</div>
```

#### Typeahead Suggestions
- **Recent Searches**: Last 10 searches for quick access
- **Popular Terms**: Most frequently searched terms
- **SKU Suggestions**: Auto-complete for partial SKU matches
- **Store Names**: Auto-complete for store selection
- **Category Names**: Auto-complete for category selection

#### Advanced Filters Panel
- **Collapsible sidebar** with filter groups
- **Filter chips** showing active filters with remove option
- **Clear All** and **Apply** buttons
- **Filter presets** for common searches (e.g., "High Discount Deals")

#### Results Display
- **Card-based layout** with consistent formatting
- **Search term highlighting** in results
- **Result type badges** (Product, Alert, Category, etc.)
- **Relevance score** display (optional, for debugging)
- **Quick action buttons** (View, Edit, Delete) per result

#### Search State Management
- **URL preservation** of search query and filters
- **Browser back/forward** navigation support
- **Search history** persistence across sessions
- **Bookmarkable searches** for important queries

### Performance Requirements

#### Response Times
- **Typeahead**: < 100ms
- **Simple search**: < 200ms
- **Complex filtered search**: < 500ms
- **Large result sets (1000+)**: < 1000ms

#### Scalability
- **Concurrent searches**: Support 20+ simultaneous users
- **Large datasets**: Efficient with 50,000+ products
- **Real-time updates**: Results update within 5 minutes of data changes
- **Caching**: 80%+ cache hit ratio for common searches

### Accessibility & Mobile

#### Accessibility
- **Keyboard navigation** for all search components
- **Screen reader** support with proper ARIA labels
- **High contrast** mode compatibility
- **Focus indicators** for all interactive elements

#### Mobile Optimization
- **Touch-friendly** search input and filters
- **Collapsible filters** for small screens
- **Swipe gestures** for result cards
- **Responsive pagination** controls

## Success Metrics

### User Experience
- **Search success rate**: > 90% (user finds what they're looking for)
- **Time to result**: < 30 seconds average
- **Search abandonment**: < 10%
- **User satisfaction**: > 4.5/5 rating

### Technical Performance
- **Query response time**: P95 < 500ms
- **Search error rate**: < 1%
- **Database query efficiency**: All queries use indexes
- **Cache hit ratio**: > 80% for repeated searches

### Business Impact
- **Search usage**: Increase in search feature adoption
- **Product discovery**: Higher product view rates from search
- **Deal identification**: Faster deal discovery through search
- **Operational efficiency**: Reduced time to find specific items/issues