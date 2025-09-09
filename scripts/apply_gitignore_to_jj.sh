#!/bin/zsh

# Script to apply .gitignore entries to jj by untracking matching files
# Usage: ./apply_gitignore_to_jj.sh

set -e  # Exit on error

echo "🔍 Reading .gitignore and untracking matching files in jj..."

# Function to process gitignore patterns and find matching files
process_gitignore_pattern() {
    local pattern="$1"
    
    # Skip empty lines and comments
    if [[ -z "$pattern" ]] || [[ "$pattern" == \#* ]]; then
        return
    fi
    
    echo "📋 Processing pattern: $pattern"
    
    # Handle different gitignore pattern types
    if [[ "$pattern" == \*\*/* ]]; then
        # Pattern like **/__pycache__/ - find all matching directories
        local dirname="${pattern#\*\*/}"
        dirname="${dirname%/}"  # Remove trailing slash if present
        
        # Find all matching directories
        find . -type d -name "$dirname" 2>/dev/null | while read -r dir; do
            if [[ -e "$dir" ]]; then
                echo "  ↳ Untracking: $dir"
                jj file untrack "$dir" 2>/dev/null || echo "    ⚠️  Already untracked or not in working copy: $dir"
            fi
        done
        
    elif [[ "$pattern" == /* ]]; then
        # Pattern starts with / - root-relative path
        local path="${pattern#/}"  # Remove leading slash
        
        if [[ -e "$path" ]]; then
            echo "  ↳ Untracking: $path"
            jj file untrack "$path" 2>/dev/null || echo "    ⚠️  Already untracked or not in working copy: $path"
        else
            echo "  ↳ Path not found: $path"
        fi
        
    elif [[ "$pattern" == *\** ]] || [[ "$pattern" == *\?* ]]; then
        # Pattern contains wildcards - use find with pattern
        # Convert gitignore pattern to find pattern
        local find_pattern="$pattern"
        
        # Use find to locate matching files
        find . -name "$find_pattern" 2>/dev/null | while read -r file; do
            if [[ -e "$file" ]]; then
                echo "  ↳ Untracking: $file"
                jj file untrack "$file" 2>/dev/null || echo "    ⚠️  Already untracked or not in working copy: $file"
            fi
        done
        
    else
        # Simple pattern - check if file/directory exists
        if [[ -e "$pattern" ]]; then
            echo "  ↳ Untracking: $pattern"
            jj file untrack "$pattern" 2>/dev/null || echo "    ⚠️  Already untracked or not in working copy: $pattern"
        else
            # Try to find files matching this pattern as a name
            find . -name "$pattern" 2>/dev/null | while read -r file; do
                if [[ -e "$file" ]]; then
                    echo "  ↳ Untracking: $file"
                    jj file untrack "$file" 2>/dev/null || echo "    ⚠️  Already untracked or not in working copy: $file"
                fi
            done
        fi
    fi
}

# Alternative simpler approach - use jj directly with glob patterns
simple_untrack() {
    local pattern="$1"
    
    # Skip empty lines and comments
    if [[ -z "$pattern" ]] || [[ "$pattern" == \#* ]]; then
        return
    fi
    
    echo "📋 Processing pattern: $pattern"
    
    # Convert gitignore pattern to jj file pattern
    local jj_pattern="$pattern"
    
    # Remove leading slash for absolute paths
    if [[ "$pattern" == /* ]]; then
        jj_pattern="${pattern#/}"
    fi
    
    # Try to untrack using the pattern directly
    # jj should handle glob patterns
    echo "  ↳ Attempting to untrack pattern: $jj_pattern"
    jj file untrack "$jj_pattern" 2>&1 | while IFS= read -r line; do
        if [[ "$line" == *"Error"* ]] || [[ "$line" == *"error"* ]]; then
            echo "    ⚠️  $line"
        elif [[ -n "$line" ]]; then
            echo "    ✓ $line"
        fi
    done || true
}

# Go to the script's parent directory (the repo root)
cd "$(dirname "$0")/.." || exit 1


# Check if .gitignore exists
if [[ ! -f .gitignore ]]; then
    echo "❌ Error: .gitignore file not found in current directory"
    exit 1
fi

echo ""
echo "Method 1: Using direct pattern matching with jj"
echo "================================================"

# Read .gitignore line by line and process each pattern
while IFS= read -r line; do
    # Trim whitespace
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    
    simple_untrack "$line"
done < .gitignore

echo ""
echo "Method 2: Finding and untracking specific files"
echo "================================================"

# Process each pattern to find actual files
while IFS= read -r line; do
    # Trim whitespace
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    
    process_gitignore_pattern "$line"
done < .gitignore

echo ""
echo "✅ Finished processing .gitignore patterns"
echo ""
echo "💡 Tips:"
echo "   - Files must be in .gitignore before they can be untracked"
echo "   - Use 'jj status' to see which files are currently tracked"
echo "   - Use 'jj file list' to see all tracked files"
