"""Browser fingerprint randomization for anti-bot evasion.

Implements canvas, WebGL, audio context, and other fingerprint
randomization techniques for Playwright browsers.
"""

import logging
import random
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class FingerprintRandomizer:
    """
    Randomizes browser fingerprints to avoid detection.
    
    Features:
    - Canvas fingerprint randomization
    - WebGL fingerprint variation
    - Audio context fingerprinting
    - Screen resolution rotation
    - Timezone randomization
    - Language/locale variation
    """
    
    def __init__(self):
        """Initialize fingerprint randomizer."""
        # Common screen resolutions
        self.screen_resolutions = [
            (1920, 1080),
            (1366, 768),
            (1536, 864),
            (1440, 900),
            (1600, 900),
            (1280, 720),
            (2560, 1440),
        ]
        
        # Common timezones
        self.timezones = [
            "America/New_York",
            "America/Chicago",
            "America/Denver",
            "America/Los_Angeles",
            "America/Phoenix",
            "Europe/London",
            "Europe/Paris",
            "Europe/Berlin",
        ]
        
        # Languages
        self.languages = [
            "en-US",
            "en-GB",
            "en-CA",
            "es-US",
            "fr-FR",
            "de-DE",
        ]
    
    def get_random_fingerprint(self) -> Dict[str, Any]:
        """
        Generate random fingerprint configuration.
        
        Returns:
            Dict with fingerprint settings
        """
        width, height = random.choice(self.screen_resolutions)
        
        return {
            "viewport": {
                "width": width,
                "height": height,
            },
            "screen": {
                "width": width,
                "height": height,
            },
            "timezone": random.choice(self.timezones),
            "locale": random.choice(self.languages),
            "color_scheme": random.choice(["light", "dark"]),
            "reduced_motion": random.choice([True, False]),
        }
    
    def get_playwright_context_options(self) -> Dict[str, Any]:
        """
        Get Playwright context options with randomized fingerprint.
        
        Returns:
            Dict of Playwright context options
        """
        fingerprint = self.get_random_fingerprint()
        
        return {
            "viewport": fingerprint["viewport"],
            "locale": fingerprint["locale"],
            "timezone_id": fingerprint["timezone"],
            "color_scheme": fingerprint["color_scheme"],
            "reduced_motion": fingerprint["reduced_motion"],
            "screen": fingerprint["screen"],
        }
    
    def get_stealth_scripts(self) -> List[str]:
        """
        Get JavaScript scripts to inject for fingerprint randomization.
        
        Returns:
            List of JavaScript code strings to inject
        """
        scripts = []
        
        # Canvas fingerprint randomization
        scripts.append("""
        (function() {
            const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function() {
                const context = this.getContext('2d');
                if (context) {
                    const imageData = context.getImageData(0, 0, this.width, this.height);
                    for (let i = 0; i < imageData.data.length; i += 4) {
                        imageData.data[i] += Math.floor(Math.random() * 3) - 1;
                    }
                    context.putImageData(imageData, 0, 0);
                }
                return originalToDataURL.apply(this, arguments);
            };
        })();
        """)
        
        # WebGL fingerprint randomization
        scripts.append("""
        (function() {
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) { // UNMASKED_VENDOR_WEBGL
                    return 'Intel Inc.';
                }
                if (parameter === 37446) { // UNMASKED_RENDERER_WEBGL
                    return 'Intel Iris OpenGL Engine';
                }
                return getParameter.apply(this, arguments);
            };
        })();
        """)
        
        # Navigator properties
        scripts.append("""
        (function() {
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
        })();
        """)
        
        # Chrome object
        scripts.append("""
        (function() {
            window.chrome = {
                runtime: {}
            };
        })();
        """)
        
        return scripts
    
    def apply_to_playwright_page(self, page) -> None:
        """
        Apply fingerprint randomization to a Playwright page.
        
        Args:
            page: Playwright page object
        """
        try:
            # Add stealth scripts
            for script in self.get_stealth_scripts():
                page.add_init_script(script)
            
            logger.debug("Applied fingerprint randomization to Playwright page")
        
        except Exception as e:
            logger.warning(f"Error applying fingerprint randomization: {e}")


# Global fingerprint randomizer instance
fingerprint_randomizer = FingerprintRandomizer()
