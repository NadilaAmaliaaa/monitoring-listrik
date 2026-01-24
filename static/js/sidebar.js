// sidebar.js

class Sidebar {
  constructor() {
    this.sidebar = document.getElementById('sidebar');
    this.toggleBtn = document.getElementById('sidebarToggle');
    this.navItems = document.querySelectorAll('.nav-item');
    this.isMinimized = false;
    
    // Load saved state from localStorage
    this.loadState();
    
    // Initialize
    this.init();
  }

  init() {
    // Toggle button click
    if (this.toggleBtn) {
      this.toggleBtn.addEventListener('click', () => this.toggle());
    }

    // Set active nav based on current page
    this.setActivePage();

    // Add tooltips to nav items when minimized
    this.addTooltips();

    // Handle window resize
    window.addEventListener('resize', () => this.handleResize());
  }

  toggle() {
    this.isMinimized = !this.isMinimized;
    
    if (this.isMinimized) {
      this.sidebar.classList.add('minimized');
    } else {
      this.sidebar.classList.remove('minimized');
    }

    // Save state to localStorage
    this.saveState();

    // Dispatch custom event
    window.dispatchEvent(new CustomEvent('sidebarToggle', { 
      detail: { isMinimized: this.isMinimized } 
    }));
  }

  minimize() {
    if (!this.isMinimized) {
      this.toggle();
    }
  }

  expand() {
    if (this.isMinimized) {
      this.toggle();
    }
  }

  setActivePage() {
    const currentPath = window.location.pathname;
    
    this.navItems.forEach(item => {
      item.classList.remove('active');
      
      const href = item.getAttribute('href');
      if (href === currentPath || (currentPath === '/' && href === '/')) {
        item.classList.add('active');
      }
    });
  }

  addTooltips() {
    this.navItems.forEach(item => {
      const text = item.querySelector('.nav-text');
      if (text) {
        item.setAttribute('data-tooltip', text.textContent);
      }
    });
  }

  saveState() {
    localStorage.setItem('sidebarMinimized', this.isMinimized);
  }

  loadState() {
    const saved = localStorage.getItem('sidebarMinimized');
    if (saved === 'true') {
      this.isMinimized = true;
      this.sidebar.classList.add('minimized');
    }
  }

  handleResize() {
    // Handle responsive behavior
    if (window.innerWidth < 1024) {
      this.sidebar.classList.remove('minimized');
    }
  }

  // Mobile menu toggle
  openMobile() {
    this.sidebar.classList.add('mobile-open');
    this.createOverlay();
  }

  closeMobile() {
    this.sidebar.classList.remove('mobile-open');
    this.removeOverlay();
  }

  createOverlay() {
    if (!document.getElementById('sidebarOverlay')) {
      const overlay = document.createElement('div');
      overlay.id = 'sidebarOverlay';
      overlay.style.cssText = `
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.5);
        z-index: 999;
        animation: fadeIn 0.2s ease;
      `;
      overlay.addEventListener('click', () => this.closeMobile());
      document.body.appendChild(overlay);
    }
  }

  removeOverlay() {
    const overlay = document.getElementById('sidebarOverlay');
    if (overlay) {
      overlay.remove();
    }
  }
}

// Initialize sidebar when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
  window.sidebarInstance = new Sidebar();
});

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
  module.exports = Sidebar;
}