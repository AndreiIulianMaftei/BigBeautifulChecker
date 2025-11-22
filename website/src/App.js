import React, { useEffect, useState, useRef } from 'react';
import './App.css';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

function App() {
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [processedImages, setProcessedImages] = useState([]);
  const [showResults, setShowResults] = useState(false);
  const fileInputRef = useRef(null);

  const handleStartClick = () => {
    setIsTransitioning(true);
    setTimeout(() => {
      setShowUpload(true);
    }, 800);
  };

  useEffect(() => {
    if (processedImages.length > 0) {
      const timeout = setTimeout(() => setShowResults(true), 300);
      return () => clearTimeout(timeout);
    }
  }, [processedImages.length]);

  const handleViewUpload = () => {
    setShowResults(false);
  };

  const uploadFile = async (file) => {
    const data = new FormData();
    data.append('file', file);

    const response = await fetch(`${API_BASE_URL}/detect`, {
      method: 'POST',
      body: data,
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || 'Failed to process file');
    }

    const payload = await response.json();
    return {
      id: `${file.name}-${Date.now()}`,
      fileName: file.name,
      annotations: payload?.result?.annotation || [],
      imageSrc: payload?.annotated_image_base64
        ? `data:image/png;base64,${payload.annotated_image_base64}`
        : null,
    };
  };

  const handleFileChange = async (event) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) {
      return;
    }

    setErrorMessage('');
    setIsUploading(true);

    try {
      const uploadResults = await Promise.all(files.map(uploadFile));
      setProcessedImages((prev) => [...uploadResults, ...prev]);
    } catch (error) {
      console.error('Upload error:', error);
      setErrorMessage(error.message || 'Unable to process the selected files.');
    } finally {
      setIsUploading(false);
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

      <div className={`upload-section ${showUpload && !showResults ? 'show' : ''}`}>
        <div className="upload-container">
          <div className="upload-header">
            <p className="eyebrow">Step 1</p>
            <h2>Upload inspection photos</h2>
            <p className="subtitle">Drag and drop multiple images or browse your computer.</p>
          </div>
          
          <div className="upload-area" onClick={() => fileInputRef.current?.click()}>
            <input
              ref={fileInputRef}
              type="file"
              id="file-upload"
              multiple
              accept="image/*,.pdf"
              onChange={handleFileChange}
              className="file-input"
            />
            <div className="upload-label">
              <p className="upload-text">Drop your files here</p>
              <p className="upload-formats">JPEG or PNG, up to 50MB each</p>
              <button
                type="button"
                className="browse-button"
                onClick={(event) => {
                  event.stopPropagation();
                  fileInputRef.current?.click();
                }}
              >
                Browse files
              </button>
              <p className="upload-hint">You can select multiple files at once</p>
            </div>
          </div>

          {isUploading && (
            <div className="status-message">Processing files…</div>
          )}

          {errorMessage && (
            <div className="error-message">{errorMessage}</div>
          )}

          {processedImages.length > 0 && !showResults && (
            <button type="button" className="secondary-button view-report" onClick={() => setShowResults(true)}>
              View latest report
            </button>
          )}
        </div>
      </div>

      <div className={`results-page ${showResults ? 'visible' : ''}`}>
        <div className="results-content">
          <div className="results-header">
            <div>
              <p className="eyebrow">Step 2</p>
              <h2>Visual report</h2>
              <p className="subtitle">Annotated results are ready. Review the detections for each photo.</p>
            </div>
            <button type="button" className="secondary-button" onClick={handleViewUpload}>
              Upload more files
            </button>
          </div>

          <div className="results-grid">
            {processedImages.map((item) => (
              <div className="result-card" key={item.id}>
                <div className="result-card__image">
                  <p className="file-name">{item.fileName}</p>
                  {item.imageSrc ? (
                    <img
                      src={item.imageSrc}
                      alt={`Processed ${item.fileName}`}
                      className="processed-image"
                    />
                  ) : (
                    <p className="no-preview">No preview available</p>
                  )}
                </div>
                <div className="annotations">
                  {item.annotations.length ? (
                    item.annotations.map((annotation, index) => (
                      <div className="annotation-item" key={`${item.id}-${index}`}>
                        <span className="annotation-label">{annotation.label}</span>
                        <span className="annotation-severity">Severity: {annotation.severity}</span>
                      </div>
                    ))
                  ) : (
                    <p className="no-annotation">No damages detected</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
