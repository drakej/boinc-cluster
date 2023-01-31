$.fn.dataTable.momentduration = function () {
    var types = $.fn.dataTable.ext.type;
 
    // Add sorting method - use an integer for the sorting
    types.order[ 'moment-duration-pre' ] = function ( d ) {
        return moment.duration( d ).asMilliseconds();
    };
};