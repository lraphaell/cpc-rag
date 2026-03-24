"""
Chunking Strategies Module

Provides different chunking strategies:
- Semantic: semantic_chunker (context-aware, uses sentence boundaries)
- Structural: structural_chunker (section/slide/row-based)
- Fixed: fixed_chunker (token-based with overlap)
"""

def get_chunker(chunking_method: str):
    """
    Get appropriate chunker based on strategy description.

    Args:
        chunking_method: Strategy description (e.g., "Semantic chunking, 500 tokens, 50 overlap")

    Returns:
        Chunker instance
    """
    method_lower = chunking_method.lower()

    if 'semantic' in method_lower:
        from .semantic_chunker import SemanticChunker
        # Extract parameters from description
        target_size = 512  # default
        overlap = 50  # default

        # Try to extract token size
        import re
        size_match = re.search(r'(\d+)[\s-]*token', method_lower)
        if size_match:
            target_size = int(size_match.group(1))

        overlap_match = re.search(r'(\d+)[\s-]*overlap', method_lower)
        if overlap_match:
            overlap = int(overlap_match.group(1))

        return SemanticChunker(target_size=target_size, overlap=overlap)

    elif any(keyword in method_lower for keyword in ['section', 'slide', 'row', 'structural']):
        from .structural_chunker import StructuralChunker
        return StructuralChunker()

    else:
        # Fallback to fixed-size chunker
        from .fixed_chunker import FixedChunker
        return FixedChunker(chunk_size=512, overlap=50)
