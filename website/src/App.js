import React, { useState } from 'react';
import './App.css';

function App() {
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [showUpload, setShowUpload] = useState(false);

  const handleStartClick = () => {
    setIsTransitioning(true);
    setTimeout(() => {
      setShowUpload(true);
    }, 800);
  };

  const handleFileChange = (event) => {
    const files = event.target.files;
    if (files.length > 0) {
      console.log('Files selected:', files);
      // Handle file upload here
    }
  };

  return (
    <div className="app">
      <img 
        src="/12312Asset 1qww21312312.svg" 
        alt="Background" 
        className="background"
      />
      
      <div className={`landing-content ${isTransitioning ? 'slide-up' : ''}`}>
        <img 
          src="/12312Asset 2qww21312312.svg" 
          alt="Crib Checker" 
          className="title"
        />
        
        <img 
          src="/12312Asset 3qww21312312.svg" 
          alt="Start now" 
          className="button"
          onClick={handleStartClick}
        />
      </div>

      <div className={`upload-section ${showUpload ? 'show' : ''}`}>
        <div className="upload-container">
          <div className="upload-header">
            <svg className="upload-icon" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M32 8C28.6863 8 26 10.6863 26 14V26H14C10.6863 26 8 28.6863 8 32C8 35.3137 10.6863 38 14 38H26V50C26 53.3137 28.6863 56 32 56C35.3137 56 38 53.3137 38 50V38H50C53.3137 38 56 35.3137 56 32C56 28.6863 53.3137 26 50 26H38V14C38 10.6863 35.3137 8 32 8Z" fill="currentColor"/>
            </svg>
            <h2>Upload files</h2>
            <p className="subtitle">Select and upload the files of your choice</p>
          </div>
          
          <div className="upload-area">
            <input
              type="file"
              id="file-upload"
              multiple
              accept="image/*,.pdf"
              onChange={handleFileChange}
              className="file-input"
            />
            <label htmlFor="file-upload" className="upload-label">
              <svg className="cloud-icon" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M52 32C52 24.268 45.732 18 38 18C37.362 18 36.734 18.044 36.118 18.13C34.082 12.328 28.516 8 22 8C13.716 8 7 14.716 7 23C7 23.338 7.01 23.674 7.028 24.008C3.156 25.804 0.5 29.706 0.5 34.25C0.5 40.463 5.537 45.5 11.75 45.5H50.25C56.463 45.5 61.5 40.463 61.5 34.25C61.5 28.037 56.463 23 50.25 23C50.168 23 50.086 23.001 50.004 23.003C51.254 26.011 52 29.416 52 33C52 33 52 32.667 52 32Z" fill="currentColor"/>
                <path d="M32 28L32 44M32 28L26 34M32 28L38 34" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              <p className="upload-text">Choose a file or drag & drop it here</p>
              <p className="upload-formats">JPEG, PNG, PDG, and MP4 formats, up to 50MB</p>
              <button type="button" className="browse-button">Browse File</button>
            </label>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
