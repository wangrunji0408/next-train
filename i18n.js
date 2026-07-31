class I18n {
    constructor() {
        this.currentLang = this.detectLanguage();
        this.translations = {};
        this.init();
    }

    detectLanguage() {
        // Check localStorage first
        const savedLang = localStorage.getItem('language');
        if (savedLang && ['zh', 'en'].includes(savedLang)) {
            return savedLang;
        }

        // Check browser language
        const browserLang = navigator.language || navigator.userLanguage;
        if (browserLang.startsWith('zh')) {
            return 'zh';
        } else {
            return 'en';
        }
    }

    init() {
        this.translations = {
            zh: {
                // Header
                appTitle: '下班车时间',
                
                // Loading and status
                locating: '正在定位中...',
                calculating: '计算中...',
                noService: '已停运',
                trainTimeDefault: '--:--',
                
                // Location and permissions
                locationNotSupported: '您的设备不支持定位功能',
                locationPermissionDenied: '定位权限被拒绝',
                locationUnavailable: '位置信息不可用',
                locationTimeout: '定位超时',
                locationFailed: '定位失败',
                
                // Station info
                distanceAway: '距离您 {distance} 米',
                selectedStation: '已选择的地铁站',
                nearbyStations: '附近车站',
                allStations: '全部车站',
                
                // Controls and buttons
                selectByDistance: '按距离选择站点',
                searchStation: '输入站名',
                back: '返回',
                
                // Train info
                nextTrainTo: '开往 {destination}',
                departsIn: '{minutes} 分 {seconds} 秒后发车',
                departsInSeconds: '{seconds} 秒后发车',
                departing: '即将发车',
                trainDeparted: '已发车',
                lineNumber: '{number}号线',
                lineNameNumeric: '{number}号线',
                lineNameNonNumeric: '{name}线',
                firstTrain: '首',
                lastTrain: '末',
                
                // Search and input
                enterStationName: '输入地铁站名：',
                searchPlaceholder: '输入地铁站名搜索...',
                noLocationFallback: '无法获取定位，请输入地铁站名：',
                
                // Error messages
                dataLoadFailed: '加载数据失败',
                cannotLoadData: '无法加载数据',
                
                // Language selector
                language: '语言',
                chinese: '中文',
                english: 'English'
            },
            en: {
                // Header
                appTitle: 'Next Train',
                
                // Loading and status
                locating: 'Locating...',
                calculating: 'Calculating...',
                noService: 'Service ended',
                trainTimeDefault: '--:--',
                
                // Location and permissions
                locationNotSupported: 'Your device does not support location',
                locationPermissionDenied: 'Location permission denied',
                locationUnavailable: 'Location information unavailable',
                locationTimeout: 'Location timeout',
                locationFailed: 'Location failed',
                
                // Station info
                distanceAway: '{distance}m away',
                selectedStation: 'Selected station',
                nearbyStations: 'Nearby stations',
                allStations: 'All stations',
                
                // Controls and buttons
                selectByDistance: 'Select station by distance',
                searchStation: 'Search station',
                back: 'Back',
                
                // Train info
                nextTrainTo: 'To {destination}',
                departsIn: 'Departs in {minutes}m {seconds}s',
                departsInSeconds: 'Departs in {seconds}s',
                departing: 'Departing soon',
                trainDeparted: 'Departed',
                lineNumber: 'Line {number}',
                lineNameNumeric: 'Line {number}',
                lineNameNonNumeric: '{name} Line',
                firstTrain: '1st',
                lastTrain: 'Last',
                
                // Search and input
                enterStationName: 'Enter station name:',
                searchPlaceholder: 'Search station name...',
                noLocationFallback: 'Unable to get location, please enter station name:',
                
                // Error messages
                dataLoadFailed: 'Failed to load data',
                cannotLoadData: 'Cannot load data',
                
                // Language selector
                language: 'Language',
                chinese: '中文',
                english: 'English'
            }
        };
    }

    t(key, params = {}) {
        const translation = this.translations[this.currentLang][key] || key;
        
        // Replace parameters in translation
        return translation.replace(/{(\w+)}/g, (match, paramKey) => {
            return params[paramKey] || match;
        });
    }

    setLanguage(lang) {
        if (['zh', 'en'].includes(lang)) {
            this.currentLang = lang;
            localStorage.setItem('language', lang);
            
            // Update document lang attribute
            document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en-US';
            
            // Trigger language change event
            window.dispatchEvent(new CustomEvent('languageChanged', { detail: { language: lang } }));
        }
    }

    getCurrentLanguage() {
        return this.currentLang;
    }

    getSupportedLanguages() {
        return [
            { code: 'zh', name: this.t('chinese') },
            { code: 'en', name: this.t('english') }
        ];
    }
}

// Create global instance
window.i18n = new I18n();