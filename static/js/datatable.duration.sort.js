$.fn.dataTable.momentduration = function () {
    var types = $.fn.dataTable.ext.type;
 
    // Add type detection
    // types.detect.unshift( function ( d ) {
    //     return moment.duration( d ).isValid() ?
    //         'moment-duration' :
    //         null;
    // } );
 
    // Add sorting method - use an integer for the sorting
    types.order[ 'moment-duration-pre' ] = function ( d ) {
        return moment.duration( d ).asMilliseconds();
    };
};