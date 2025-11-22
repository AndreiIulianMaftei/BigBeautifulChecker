import React, { useEffect, useMemo, useRef, useState } from 'react';
import './App.css';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const COST_HORIZONS = [5, 10, 15];

const clampSeverity = (value) => {
  const parsed = parseInt(value, 10);
  if (Number.isNaN(parsed)) {
    return 3;
  }
  return Math.min(5, Math.max(1, parsed));
};

const formatCurrency = (value) => {
  const formatter = new Intl.NumberFormat('de-CH', {
    style: 'currency',
    currency: 'CHF',
    maximumFractionDigits: 0,
  });
  return formatter.format(value || 0);
};

const buildSyntheticItems = (fileName) => {
  const seed = (fileName || 'structure')
    .split('')
    .reduce((acc, char) => acc + char.charCodeAt(0), 0);
  const templates = ['Building envelope', 'Utilities & fixtures', 'Interior surfaces'];
  return templates.map((label, index) => ({
    item: `${label} (${fileName || 'zone'})`,
    severity: ((seed + index * 37) % 5) + 1,
  }));
};

const createMockDamageItems = (annotations = [], fileName = '') => {
  const derivedFromModel = annotations
    .map((annotation, index) => ({
      item: annotation.label || `Damage ${index + 1}`,
      severity: clampSeverity(annotation.severity ?? 3),
    }))
    .filter((annotation) => Boolean(annotation.item));

  if (derivedFromModel.length >= 2) {
    return derivedFromModel.slice(0, 3);
  }

  const syntheticFallback = buildSyntheticItems(fileName);
  return [...derivedFromModel, ...syntheticFallback].slice(0, 3);
};

const normalizeBackendSeries = (yearlyCosts = []) =>
  yearlyCosts
    .map((row) => ({
      year: Number(row.year) || 0,
      cost: Number(row.cost) || 0,
      scheduled_work: row.scheduled_work || row.notes || 'Scheduled work',
    }))
    .filter((row) => row.year > 0);

const generateSyntheticSeries = (label, severity) => {
  const seed = (label || 'damage').split('').reduce((acc, char) => acc + char.charCodeAt(0), severity * 97);
  const baseCost = 700 + severity * 450;
  return Array.from({ length: 15 }, (_, index) => {
    const year = index + 1;
    const noise = Math.abs(Math.sin(seed + year * 12.9898));
    let cost = 0;
    if ([5, 10, 15].includes(year)) {
      cost = baseCost * (1.1 + noise * 0.6 + severity * 0.15);
    } else if (noise > 0.85 || year % Math.max(2, 6 - severity) === 0) {
      cost = baseCost * 0.35 * (0.5 + noise);
    }

    return {
      year,
      cost: Math.round(cost),
      scheduled_work: cost ? (year % 5 === 0 ? 'Planned intervention' : 'Condition-based service') : 'No work scheduled',
    };
  });
};

const mergeSeries = (syntheticSeries, backendSeries) => {
  if (!backendSeries.length) {
    return syntheticSeries;
  }

  const backendMap = new Map();
  backendSeries.forEach((row) => {
    backendMap.set(row.year, row);
  });

  return syntheticSeries.map((entry) => {
    const backendRow = backendMap.get(entry.year);
    if (!backendRow || backendRow.cost <= 0) {
      return entry;
    }
    return {
      ...entry,
      cost: Math.round(backendRow.cost),
      scheduled_work: backendRow.scheduled_work,
    };
  });
};

const buildPricingProfiles = (damageItems, pricingResponse) => {
  const analysesMap = new Map();
  pricingResponse?.analyses?.forEach((analysis) => {
    const key = (analysis.damage_item || '').toLowerCase();
    analysesMap.set(key, analysis);
  });

  return damageItems.map((damage, index) => {
    const analysis = analysesMap.get((damage.item || '').toLowerCase());
    const backendSeries = normalizeBackendSeries(analysis?.ten_year_projection?.yearly_costs);
    const syntheticSeries = generateSyntheticSeries(damage.item || `Damage ${index + 1}`, damage.severity);
    const mergedSeries = mergeSeries(syntheticSeries, backendSeries);

    const horizons = COST_HORIZONS.map((year) => ({
      year,
      total: Math.round(
        mergedSeries.filter((entry) => entry.year <= year).reduce((sum, entry) => sum + entry.cost, 0)
      ),
    }));

    const maxHorizon = Math.max(...horizons.map((h) => h.total), 1);
    const maxYearly = Math.max(...mergedSeries.map((entry) => entry.cost), 1);

    return {
      label: damage.item,
      severity: damage.severity,
      category: analysis?.complete_data?.Category || 'General system',
      horizons,
      yearlySeries: mergedSeries,
      maxHorizon,
      maxYearly,
    };
  });
};

function App() {
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [processedImages, setProcessedImages] = useState([]);
  const [showResults, setShowResults] = useState(false);
  const [selectedImageId, setSelectedImageId] = useState(null);
  const fileInputRef = useRef(null);

  const selectedImage = useMemo(
    () => processedImages.find((image) => image.id === selectedImageId) || null,
    [processedImages, selectedImageId]
  );

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
    setSelectedImageId(null);
  };

  const handleOpenDetail = (imageId) => {
    setSelectedImageId(imageId);
  };

  const handleCloseDetail = () => {
    setSelectedImageId(null);
  };

  const fetchPricing = async (damageItems) => {
    if (!damageItems.length) {
      return null;
    }

    const response = await fetch(`${API_BASE_URL}/calculate-price`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        damage_items: damageItems,
        use_mock: true,
        max_concurrent: Math.min(3, damageItems.length),
      }),
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || 'Failed to calculate pricing');
    }

    return response.json();
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
    const annotations = payload?.result?.annotation || [];
    const mockDamageItems = createMockDamageItems(annotations, file.name);

    let pricing = null;
    try {
      pricing = await fetchPricing(mockDamageItems);
    } catch (pricingError) {
      console.warn('Pricing generation failed:', pricingError);
    }

    const costProfiles = buildPricingProfiles(mockDamageItems, pricing);

    return {
      id: `${file.name}-${Date.now()}`,
      fileName: file.name,
      annotations,
      imageSrc: payload?.annotated_image_base64
        ? `data:image/png;base64,${payload.annotated_image_base64}`
        : null,
      mockDamageItems,
      pricing,
      costProfiles,
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
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
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

                <div className="result-actions">
                  <div>
                    <p className="metric-label">Damages located</p>
                    <p className="result-count">{item.annotations.length || 0}</p>
                  </div>
                  <button type="button" className="primary-button" onClick={() => handleOpenDetail(item.id)}>
                    View cost insights
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {selectedImage && (
        <div className={`detail-overlay ${selectedImage ? 'visible' : ''}`}>
          <div className="detail-panel">
            <button type="button" className="close-detail" onClick={handleCloseDetail}>
              Close
            </button>
            <div className="detail-header">
              <div className="detail-preview">
                {selectedImage.imageSrc ? (
                  <img src={selectedImage.imageSrc} alt={selectedImage.fileName} />
                ) : (
                  <div className="detail-placeholder">Preview unavailable</div>
                )}
              </div>
              <div className="detail-meta">
                <p className="eyebrow">Cost insights</p>
                <h3>{selectedImage.fileName}</h3>
                <p className="subtitle">
                  {selectedImage.costProfiles?.length || 0} damage categories analyzed over 5, 10 and 15 years.
                </p>
              </div>
            </div>

            <div className="detail-content">
              {selectedImage.costProfiles?.map((profile) => (
                <div className="detail-card" key={`${selectedImage.id}-${profile.label}`}>
                  <div className="analysis-card__header">
                    <div>
                      <p className="analysis-title">{profile.label}</p>
                      <p className="analysis-subtitle">{profile.category}</p>
                    </div>
                    <span className={`severity-pill severity-${profile.severity}`}>
                      Severity {profile.severity}/5
                    </span>
                  </div>

                  <div className="horizon-bars">
                    {profile.horizons.map((horizon) => (
                      <div className="horizon-bar" key={`${profile.label}-${horizon.year}`}>
                        <div className="horizon-bar__label">{horizon.year}-year</div>
                        <div className="horizon-bar__track">
                          <div
                            className="horizon-bar__fill"
                            style={{
                              width: `${Math.min(
                                100,
                                Math.max(0, (horizon.total / profile.maxHorizon) * 100)
                              )}%`,
                            }}
                          />
                        </div>
                        <div className="horizon-bar__value">{formatCurrency(horizon.total)}</div>
                      </div>
                    ))}
                  </div>

                  <div className="analysis-meta">
                    <div>
                      <p className="meta-label">Highest year</p>
                      <p className="meta-value">
                        {formatCurrency(
                          Math.max(...profile.yearlySeries.map((entry) => entry.cost), 0)
                        )}
                      </p>
                    </div>
                    <div>
                      <p className="meta-label">Active years</p>
                      <p className="meta-value">
                        {profile.yearlySeries.filter((entry) => entry.cost > 0).length}
                      </p>
                    </div>
                  </div>

                  <div className="yearly-chart">
                    {profile.yearlySeries.map((entry) => (
                      <div className="year-bar" key={`${profile.label}-${entry.year}`}>
                        <div
                          className="year-bar__fill"
                          style={{
                            height: `${Math.min(
                              100,
                              Math.max(0, (entry.cost / profile.maxYearly) * 100)
                            )}%`,
                          }}
                          title={`Year ${entry.year}: ${formatCurrency(entry.cost)}`}
                        />
                        <span className="year-bar__label">{entry.year}</span>
                      </div>
                    ))}
                  </div>

                  <p className="projection-summary">
                    {profile.yearlySeries.find((entry) => entry.cost > 0)?.scheduled_work ||
                      'No major maintenance expected in this horizon.'}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
